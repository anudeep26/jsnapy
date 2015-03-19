#!/Library/Frameworks/Python.framework/Versions/2.7/Resources/Python.app/Contents/MacOS/Python

import sys
import os
import shutil
import textwrap
import argparse
from distutils.sysconfig import get_python_lib
import yaml
from jnpr.jsnap.snap import Parse
from jnpr.jsnap.check import Comparator
from jnpr.jsnap.notify import Notification
from threading import Thread
from jnpr.junos import Device
import distutils.dir_util
import colorama


class Jsnap:

    # taking parameters from command line
    def __init__(self):
        colorama.init(autoreset=True)
        self.parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=textwrap.dedent('''\
                                        Tool to capture snapshots and compare them
                                        It supports five subcommands:
                                        --init, --snap, --check, --snapcheck, --diff
                                        1. Generate init folder:
                                                jsnap --init
                                        2. Overwrite folders generated by init:
                                                jsnap --init -o
                                        3. Take snapshot:
                                                jsnap --snap pre_snapfile -f main_configfile
                                        4. Compare snapshots:
                                                jsnap --check post_snapfile pre_snapfile -f main_configfile
                                        5. Compare current configuration:
                                                jsnap --snapcheck snapfile -f main_configfile
                                        6. Take diff without specifying test case:
                                                jsnap --diff pre_snapfile post_snapfile -f main_configfile
                                            '''),
            usage="\n This tool enables you to capture and audit runtime environment snapshots of your "
            "networked devices running the Junos operating system (Junos OS)\n")

        group = self.parser.add_mutually_exclusive_group()
        # for mutually exclusive gp, can not use two or more options at a time
        group.add_argument(
            '--snap',
            action='store_true',
            help="take the snapshot for commands specified in test file")
        group.add_argument(
            '--check',
            action='store_true',
            help=" compare pre and post snapshots based on test operators specified in test file")
        group.add_argument(
            '--snapcheck',
            action='store_true',
            help='check current snapshot based on test file')
        group.add_argument(
            "--init",
            action="store_true",
            help="generate init folders: snapshots, configs and main.yml",
        )
        group.add_argument(
            "--diff",
            action="store_true",
            help="display difference between two snapshots"
        )

        self.parser.add_argument(
            "pre_snapfile",
            nargs='?',
            help="pre snapshot filename")       # make it optional
        self.parser.add_argument(
            "post_snapfile",
            nargs='?',
            help="post snapshot filename",
            type=str)       # make it optional
        self.parser.add_argument(
            "-f", "--file",
            help="config file to take snapshot",
            type=str)
        self.parser.add_argument("-t", "--hostname", help="hostname", type=str)
        self.parser.add_argument(
            "-p",
            "--passwd",
            help="password to login",
            type=str)
        self.parser.add_argument(
            "-l",
            "--login",
            help="username to login",
            type=str)
        self.parser.add_argument(
            "-m",
            "--mail",
            help="mail result to given id",
            type=str)
        self.parser.add_argument(
            "-o",
            "--overwrite",
            action='store_true',
            help="overwrite directories and files generated by init",
        )

        self.args = self.parser.parse_args()

        if len(sys.argv) == 1:
            self.parser.print_help()
            sys.exit(1)
        self.db_name = ""



    # call hosts class, connect hosts and get host list
    # use pre_snapfile because always first file is pre_snapfile regardless of
    # its name
    def get_hosts(self):
        output_file = self.args.pre_snapfile
        conf_file = self.args.file
        config_file = open(conf_file, 'r')
        self.main_file = yaml.load(config_file)

        # Sqlite changes
        self.store_in_sqlite = self.main_file['store_in_sqlite']
        self.check_from_sqlite = self.main_file['check_from_sqlite']
        if self.store_in_sqlite or self.check_from_sqlite:
            self.db_name = self.main_file['database_name']
        ###
        self.login(output_file)

    # call to generate snap files
    def generate_rpc_reply(self, dev, snap_files, username):
        test_files = []
        for tfile in self.main_file['tests']:
            if not os.path.isfile(tfile):
                tfile = os.path.join(os.getcwd(), 'configs', tfile)
            test_file = open(tfile, 'r')
            test_files.append(yaml.load(test_file))
        g = Parse()
        for tests in test_files:
            g.generate_reply(tests, dev, snap_files, self.store_in_sqlite, username, self.db_name)

    # called by check and snapcheck argument, to compare snap files
    def compare_tests(self, hostname):
        comp = Comparator()
        chk = self.args.check
        diff = self.args.diff
        if (chk or diff):
            test_obj = comp.generate_test_files(
                self.main_file,
                hostname,
                chk,
                diff,
                self.check_from_sqlite,
                self.db_name,
                self.args.pre_snapfile,
                self.args.post_snapfile)
        else:
            test_obj = comp.generate_test_files(
                self.main_file,
                hostname,
                chk,
                diff,
                self.check_from_sqlite,
                self.db_name,
                self.args.pre_snapfile)
        return test_obj

    def login(self, output_file):

        self.host_list = []
        if self.args.hostname is None:
            k = self.main_file['hosts'][0]
            # when group of devices are given, searching for include keyword in
            # hosts in main.yaml file
            if k.__contains__('include'):
                #lfile = k['include']
                # print " lfile is: ", lfile
                lfile = os.path.join(os.getcwd(), 'configs', k['include'])
                login_file = open(lfile, 'r')
                dev_file = yaml.load(login_file)
                gp = k['group']

                dgroup = [i.strip() for i in gp.split(',')]
                for dgp in dev_file:
                    if dgroup[0] == 'all' or dgp in dgroup:
                        for val in dev_file[dgp]:
                            hostname = val.keys()[0]
                            self.host_list.append(hostname)
                            username = val[hostname]['username']
                            password = val[hostname]['passwd']
                            snap_files = hostname + '_' + output_file
                            t = Thread(
                                target=self.connect,
                                args=(
                                    hostname,
                                    username,
                                    password,
                                    snap_files,
                                ))
                            t.start()
                            t.join()

        # login credentials are given in main config file
            else:
                hostname = k['devices']
                username = k['username']
                password = k['passwd']
                self.host_list.append(hostname)
                snap_files = hostname + '_' + output_file
                self.connect(hostname, username, password, snap_files)

        # if login credentials are given from command line
        else:
            hostname = self.args.hostname
            password = self.args.passwd
            username = self.args.login
            self.host_list.append(hostname)
            snap_files = hostname + '_' + output_file
            self.connect(hostname, username, password, snap_files)

    # function to connect to device
    def connect(self, hostname, username, password, snap_files):
        if self.args.snap is True or self.args.snapcheck is True:
            print "connecting to device %s ................" % hostname
            dev = Device(host=hostname, user=username, passwd=password)
            dev.open()
            # print "\n going for snapshots"
            self.generate_rpc_reply(dev, snap_files, username)
        if self.args.check is True or self.args.snapcheck is True or self.args.diff is True:
            # print "\n &&&&& going for comparision"
            testobj = self.compare_tests(hostname)
            if self.main_file.get("mail"):
                send_mail = Notification()
                send_mail.notify(self.main_file['mail'], hostname, testobj)

    # generate init folder
    def generate_init(self):
        if not os.path.isdir("snapshots"):
            os.mkdir("snapshots")
        dst_config_path = os.path.join(os.getcwd(), 'configs')
        # overwrite files if given option -o or --overwrite
        if not os.path.isdir(dst_config_path) or self.args.overwrite is True:
            distutils.dir_util.copy_tree(os.path.join(get_python_lib(), 'jnpr', 'jsnap', 'configs'),
                                         dst_config_path)
        dst_main_yml = os.path.join(dst_config_path, 'main.yml')
        if not os.path.isfile(os.path.join(os.getcwd(), 'main.yml')) or self.args.overwrite is True:
            shutil.copy(dst_main_yml, os.getcwd())

    def check_arguments(self):
        if((self.args.snap is True and (self.args.pre_snapfile is None or self.args.file is None)) or
            (self.args.check is True and (self.args.pre_snapfile is None or self.args.post_snapfile is None or self.args.file is None)) or
            (self.args.snapcheck is True and (self.args.pre_snapfile is None or self.args.file is None or self.args.post_snapfile is not None)) or
            (self.args.diff is True and (
                self.args.pre_snapfile is None or self.args.post_snapfile is None))
           ):
            print(
                colorama.Fore.RED +
                "*********Arguments not given correctly, Please refer below help message!!********")
            self.parser.print_help()
            sys.exit(1)


def main():
    d = Jsnap()
    # make init folder
    d.check_arguments()
    if d.args.init is True:
        d.generate_init()
    else:
        d.get_hosts()

if __name__ == '__main__':
    main()
