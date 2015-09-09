import json
import signal
from subprocess import Popen, PIPE
import sys

from re import split
import click
from click import ClickException
import os
from two1.config import pass_config
from two1.djangobitcoin.djangobitcoin.settings import ENDPOINTS_FILE
import two1.djangobitcoin.djangobitcoin as dj_bt

ENDPOINTS_PATH = os.path.join(dj_bt.__path__[0], ENDPOINTS_FILE)


@click.command(context_settings=dict(
    ignore_unknown_options=True,
))
@click.option('--builtin', is_flag=True, help='Show built-in endpoints.')
@click.argument('args', nargs=-1)
@pass_config
def sell(config, args, port=8000, builtin=False):
    try:
        if builtin:
            show_builtins(config)
            return
        # since we allow --builtin option without arguments, we have to process arguments manually
        try:
            path, package, config = process_args(args)
        except Exception:
            click.echo('Usage: two1 sell [OPTIONS] PATH PACKAGE')
            return
        sell_item(path, package, config, port)
    except Exception as e:
        raise ClickException(e)


def pop_option(args):
    i_opt = next(((i, x) for i, x in enumerate(args) if x.startswith('--')), None)
    if not i_opt:
        return None
    idx, opt = i_opt
    val = args[idx + 1]
    del args[idx:idx + 2]
    return opt[2:], val


def process_args(args):
    config = {}
    args = list(args)
    while True:
        opt_value = pop_option(args)
        if not opt_value:
            break
        config[opt_value[0]] = opt_value[1]
    path = args[0]
    package = args[1]
    return path, package, config


def try_config_django():
    from django.conf import settings as django_settings
    if not django_settings.configured:
        django_settings.configure()
    return True


def find_process_by_attribute(attribute):
    process_list = []
    sub_proc_ps = Popen(['ps', 'auxw', ], stdout=PIPE)
    sub_proc = Popen(['grep', attribute, ], stdin=sub_proc_ps.stdout, stdout=PIPE)
    sub_proc_ps.stdout.close()
    # Discard the first line (ps aux header)
    sub_proc.stdout.readline()
    for line in sub_proc.stdout:
        # The separator for splitting is 'variable number of spaces'
        proc_info = split(" *", line.decode('utf-8').strip())
        process_list.append(proc_info[1])  # pid
    if process_list:
        return min(process_list)


def find_process():
    # gunicorn process is started gunicorn --pythonpath two1/djangobitcoin djangobitcoin.wsgi --bind 127.0.0.1:8000
    # built-in django server is started python manage.py runserver 127.0.0.1:8000
    gunicorn_pid = find_process_by_attribute('djangobitcoin.wsgi')
    if gunicorn_pid:
        return gunicorn_pid, True
    django_svr_pid = find_process_by_attribute('runserver')
    if django_svr_pid:
        return django_svr_pid, False
    return None, None


def match_endpoint(endpoint, regex):
    return regex.match(endpoint)


def find_endpoint(endpoint, package_name):
    try:
        package = __import__(package_name, fromlist=['urls'])
        urls = getattr(package, 'urls')
        match = next((x.regex.pattern for x in urls.urlpatterns if match_endpoint(endpoint, x.regex)), None)
        if match:
            return match, urls.configurator
        else:
            return None
    except Exception as e:
        click.echo('Error importing {0}: {1}'.format(package_name, e))
        return None


def update_config(package_name, package_path, pattern):
    try:
        ep_json = json.load(open(ENDPOINTS_PATH))
    except:
        if os.path.exists(ENDPOINTS_PATH):
            click.echo('endpoints configuration file {0} was corrupted, created a new one'.format(ENDPOINTS_PATH))
        ep_json = []
    package_element = next((x for x in ep_json if x['package'] == package_name), None)
    if not package_element:
        package_element = {'package': package_name, 'urls': []}
        if package_path:
            package_element['path'] = package_path
        ep_json.append(package_element)
    else:
        urls = package_element.get('urls', None)
        if urls:
            if pattern in urls:
                click.echo('Endpoint {0} is already selling'.format(pattern))
                return None
        else:
            package_element['urls'] = []
    package_element['urls'].append(pattern)
    return ep_json


def save_config(ep_json):
    # Save the file
    with open(ENDPOINTS_PATH, 'w') as outfile:
        json.dump(ep_json, outfile, indent=2)
    click.echo('Endpoints configuration updated.')
    # Check if we can restart the server
    pid, is_gunicorn = find_process()
    if is_gunicorn:
        os.kill(int(pid), signal.SIGHUP)
        click.echo('Server restarted')
    elif pid:
        click.echo('Restart the server')


def sell_item(path, package_name, config, port):
    '''
    :param item: a string indicating which endpint to sell (f.e. 'language/translate' or 'serve/kittens')
    :param params: extra parameters from the 'sell' command to be passed to the endpoint's configurator
                   they are endpoint-specific, f.e for 'serve' it can be --path ~/foo.txt
    '''
    if not try_config_django():
        return
    package_path = config.get('packagepath', None)
    if package_path:
        sys.path.append(package_path)
        del config['packagepath']
    ep_found = find_endpoint(path, package_name)
    if not ep_found:
        click.echo('Endpoint {0} not found'.format(path))
        return
    pattern, configurator = ep_found
    click.echo('Selling %s on http://127.0.0.1:%d/' % (path, port))
    # Configure endpoint passing passthrough parameters to configurator
    click.echo('Configuring {0} with {1}'.format(path, config))
    configurator(path, config)
    # If the endpoint is not up yet, make it so
    ep_json = update_config(package_name, package_path, pattern)
    if ep_json:
        save_config(ep_json)


def try_url_imports(package_name):
    try:
        package = __import__(package_name, fromlist=['urls'])
        return package.urls.urlpatterns
    except Exception as e:
        click.echo('Error importing {0}: {1}'.format(package_name, e))
        return []


def _show_builtins(config, package):
    data_format = "{:<50}|   {:<50}"
    urls = try_url_imports('two1.djangobitcoin.misc')
    for u in urls:
        config.log(data_format.format(u.regex.pattern.strip('^$'), package))


def show_builtins(config):
    dundee1_format = "{:_^50}{:_^50}"
    dundee2_format = "{:_^50}|{:_^49}"
    header_format = "{:<50}|{:<50}"
    headers = ("PATH", "   PACKAGE")
    config.log("\nBUILTINS\n")
    if not try_config_django():
        return
    dundee_data = ['' for n in range(len(headers))]
    config.log(dundee1_format.format(*dundee_data))
    config.log(header_format.format(*headers))
    config.log(dundee2_format.format(*dundee_data))
    _show_builtins(config, 'two1.djangobitcoin.misc')
    _show_builtins(config, 'two1.djangobitcoin.scipy_aas')
    _show_builtins(config, 'two1.djangobitcoin.static_serve')
