import argparse
import led_audio_controller as controller
import test_server as tester
import textwrap


def main():
    argparser = argparse.ArgumentParser('APA102 Tcp and Udp Server',
                                        formatter_class=argparse.RawTextHelpFormatter)

    argparser.add_argument('--run-tester',
                           action='store_const',
                           dest='component',
                           const=tester,
                           default=controller,
                           help=textwrap.dedent("""
        Define if the tester should be executed, else the controller will be executed
            controller: entry point for the PI logic
            tester:     simple simulation of a user, that sends commands to the controller (PI) endpoints,
                        requires a reachable server socket created by the controller"""))

    argparser.add_argument('--config',
                           action='store',
                           dest='config',
                           default='./data/config.yaml',
                           help=textwrap.dedent("""
        Provide a path to the config file, used for the setup
                        defaults to './data/config.yaml'"""))

    args = argparser.parse_args()

    args.component.main(args)


if __name__ == '__main__':
    main()
