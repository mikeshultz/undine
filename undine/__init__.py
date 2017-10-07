#!/bin/python
""" undine
    A wrapper for handling multi-archive backups with Borg
"""

from __future__ import print_function

__author__="Mike Shultz <mike@votesmart.org>"
__copyright__="Copyright (c) 2017 Vote Smart"
__version__="0.0.3"

import os, sys, argparse, socket, fasteners
from subprocess import Popen, PIPE
from envelopes import Envelope

try:
    import configparser
except ImportError:
    import ConfigParser as configparser

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

def main():
    """ Script meat """

    # Handle command line args
    parser = argparse.ArgumentParser(description='A wrapper for handling multi-archive backups with Borg')
    parser.add_argument('--dry-run', action='store_true', dest="dryrun", help="Do not actually create archives.")
    parser.add_argument('--remote-path', dest="remote_path", help="The remote path to the borg executable")
    parser.add_argument('-v', '--verbose', action='store_true', dest="verbose", help="Show output")
    parser.add_argument('-d', '--debug', action='store_true', dest="debug", help="Show debug output")
    parser.add_argument('-l', '--lock-file', dest="lockfile", default=u"/tmp/undine.lock", help="Lock file to use")
    args = parser.parse_args()

    # Config helper
    def get_bool_config(sect, key, default = False):
        try:
            conf = parser.get(sect, key)
            return conf
        except configparser.NoSectionError:
            return default

    # Deal with Python 2 and 3 differences in configparser
    def config_get(parser, section, option, default=None):
        if sys.version_info[0] == 2:
            return parser.get(section, option, default)
        else:
            return parser.get(section, option, fallback=default)

    # Config handling. 
    config_file = ""
    user_config_file = os.path.expanduser('~/.config/undine.ini')
    system_config_file = '/etc/undine.ini'
    # User ini trumps system ini
    if os.path.isfile(user_config_file):
        config_file = user_config_file
    elif os.path.isfile(system_config_file):
        config_file = system_config_file
    else:
        raise Exception("Could not find configuration ini file at ~/.config/undine.ini or /etc/undine.ini.")
    parser = configparser.ConfigParser()
    parser.read(config_file)

    config = {
        'debug': get_bool_config('default', 'debug'),
        'verbose': False,
        'repos': config_get(parser, 'default', 'repos', 'ssh://rsync//data1/home/9774/file0.ia.votesmart.org'),
        'notify_email': config_get(parser, 'default', 'notify_email', 'root@votesmart.org'),
        'lockfile': config_get(parser, 'default', 'lockfile', None) or args.lockfile,
        'units': dict(parser.items('units')),
        'hostname': config_get(parser, 'default', 'hostname', socket.gethostname()),
        'smtp_host': config_get(parser, 'smtp', 'host', 'localhost'),
        'smtp_port': config_get(parser, 'smtp', 'port', '589'),
        'smtp_login': config_get(parser, 'smtp', 'login', None),
        'smtp_password': config_get(parser, 'smtp', 'password', None),
        'smtp_tls': config_get(parser, 'smtp', 'tls', True),
    }

    # debug turns on verbose
    if config['debug']:
        config['debug'] = True
        config['verbose'] = True

    # E-mail log
    email_log = []

    # Should probably prevent multiple backups from running
    with fasteners.InterProcessLock(config['lockfile']):

        if config['verbose']:
            print('Backing up system...')

        # Handle special arguments
        extra_args = ""
        if args.dryrun:
            extra_args += "-n"
        if args.remote_path is not None:
            extra_args += "--remote-path=%s" % args.remote_path

        for name,path in config['units'].items():

            # Command we're using
            cmd = "borg create %s -C lz4 %s::%s-{now:%%Y-%%m-%%d} %s" % \
                (extra_args, config['repos'], name, path, )

            if config['debug']:
                print("Running: %s" % cmd)

            # Run the backup
            pipes = Popen(cmd, shell=True, 
                stdout=PIPE, stderr=PIPE)

            # Get output
            out, err = pipes.communicate()

            # Handle the return
            if pipes.returncode != 0:
                if config['verbose']:
                    print("Error creating archive for %s::%s" % (config['repos'], name, ), file=sys.stderr)
                email_log.append("FAIL: %s::%s" % (config['repos'], name, ))
                email_log.append(str(err))
            else:
                if config['verbose']:
                    print("Successfully created archive for %s::%s", (config['repos'], name, ))
                email_log.append("SUCCESS: %s::%s" % (config['repos'], name, ))

    if not args.dryrun and len(email_log) > 0:
        # Create E-mail
        envelope = Envelope(
            from_addr=u'root@votesmart.org',
            to_addr=u'root@votesmart.org',
            subject=u'Backup Summary for %s' % config['hostname'],
            text_body="\n".join(email_log)
        )

        # Send it
        envelope.send(config['smtp_host'], login=config['smtp_login'],
                  password=config['smtp_password'], tls=config['smtp_tls'])

    if config['verbose']:
        print('Complete!')

if __name__ == '__main__':
    main()