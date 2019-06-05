#!/usr/bin/env python3

import logging
import time

from pyhelm.tiller import Tiller

from kube_janitor import __version__, cmd, shutdown
from kube_janitor.helper import get_kube_api
from kube_janitor.janitor import clean_up
from kube_janitor.rules import load_rules_from_file

logger = logging.getLogger('janitor')


def main(args=None):
    parser = cmd.get_parser()
    args = parser.parse_args(args)

    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
                        level=logging.DEBUG if args.debug else logging.INFO)

    config_str = ', '.join(f'{k}={v}' for k, v in sorted(vars(args).items()))
    logger.info(f'Janitor v{__version__} started with {config_str}')

    if args.dry_run:
        logger.info('**DRY-RUN**: no deletions will be performed!')

    if args.rules_file:
        rules = load_rules_from_file(args.rules_file)
        logger.info(f'Loaded {len(rules)} rules from file {args.rules_file}')
    else:
        rules = []

    if args.tiller_host and args.tiller_port:
        tiller = Tiller(args.tiller_host, args.tiller_port)
    else:
        tiller = None

    return run_loop(args.once, args.include_resources, args.exclude_resources, args.include_namespaces,
                    args.exclude_namespaces, rules, args.interval, args.delete_notification, args.dry_run, tiller)


def run_loop(run_once, include_resources, exclude_resources, include_namespaces, exclude_namespaces,
             rules, interval, delete_notification, dry_run, tiller):
    handler = shutdown.GracefulShutdown()
    while True:
        try:
            api = get_kube_api()
            clean_up(
                api,
                include_resources=frozenset(include_resources.split(',')),
                exclude_resources=frozenset(exclude_resources.split(',')),
                include_namespaces=frozenset(include_namespaces.split(',')),
                exclude_namespaces=frozenset(exclude_namespaces.split(',')),
                rules=rules,
                delete_notification=delete_notification,
                dry_run=dry_run,
                tiller=tiller
            )
        except Exception as e:
            logger.exception('Failed to clean up: %s', e)
        if run_once or handler.shutdown_now:
            return
        with handler.safe_exit():
            time.sleep(interval)
