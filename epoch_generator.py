import asyncio
import json
import sys
import threading
import time
from functools import wraps
from multiprocessing import Process
from signal import SIGINT, SIGTERM, SIGQUIT, signal
from time import sleep

from redis import asyncio as aioredis
from setproctitle import setproctitle

from exceptions import GenericExitOnSignal
from helpers.message_models import RPCNodesObject
from helpers.redis_keys import get_epoch_generator_last_epoch, get_epoch_generator_epoch_history
from helpers.rpc_helper import ConstructRPC
from settings.conf import settings
from utils.default_logger import logger
from utils.redis_conn import RedisPool


def chunks(start_idx, stop_idx, n):
    run_idx = 0
    for i in range(start_idx, stop_idx + 1, n):
        # Create an index range for l of n items:
        begin_idx = i  # if run_idx == 0 else i+1
        if begin_idx == stop_idx + 1:
            return
        end_idx = i + n - 1 if i + n - 1 <= stop_idx else stop_idx
        run_idx += 1
        yield begin_idx, end_idx, run_idx


def redis_cleanup(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)
        except (GenericExitOnSignal, KeyboardInterrupt):
            try:
                self._logger.debug('Waiting for pushing latest epoch to Redis')
                if self.last_sent_block:
                    await self._writer_redis_pool.set(get_epoch_generator_last_epoch(), self.last_sent_block)

                    self._logger.debug('Shutting down after sending out last epoch with end block height as {},'
                                       ' starting blockHeight to be used during next restart is {}'
                                       , self.last_sent_block, self.last_sent_block + 1)
            except Exception as E:
                self._logger.error('Error while saving last state: {}', E)
        except Exception as E:
            self._logger.error('Error while running process: {}', E)
        finally:
            self._logger.debug('Shutting down')
            if not self._simulation_mode:
                sys.exit(0)

    return wrapper


class EpochGenerator:
    _aioredis_pool: RedisPool
    _reader_redis_pool: aioredis.Redis
    _writer_redis_pool: aioredis.Redis

    def __init__(self, name='PowerLoom|OffChainConsensus|EpochGenerator', simulation_mode=False):
        self.name = name
        setproctitle(self.name)
        self._logger = logger.bind(module=self.name)
        self._simulation_mode = simulation_mode
        self._shutdown_initiated = False
        self.last_sent_block = 0
        self._end = None

    async def setup(self, **kwargs):
        if self._simulation_mode:
            self._logger.debug('Simulation mode is on')
            if settings.test_redis:
                self._aioredis_pool = RedisPool(writer_redis_conf=settings.test_redis)
            else:
                self._logger.error('Test Redis not configured')
                sys.exit(0)
        else:
            self._aioredis_pool = RedisPool(writer_redis_conf=settings.redis)
        await self._aioredis_pool.populate()
        self._reader_redis_pool = self._aioredis_pool.reader_redis_pool
        self._writer_redis_pool = self._aioredis_pool.writer_redis_pool
        self.redis_thread: threading.Thread
        self._end = kwargs.get('end')

    def _generic_exit_handler(self, signum, sigframe):
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            raise GenericExitOnSignal

    @redis_cleanup
    async def run(self, **kwargs):
        await self.setup(**kwargs)

        begin_block_epoch = settings.ticker_begin_block if settings.ticker_begin_block else 0
        for signame in [SIGINT, SIGTERM, SIGQUIT]:
            signal(signame, self._generic_exit_handler)
        last_block_data_redis = await self._writer_redis_pool.get(name=get_epoch_generator_last_epoch())
        if last_block_data_redis:
            # Can't provide begin block which previous state is present in redis
            if begin_block_epoch != 0:
                self._logger.debug(
                    'Last epoch block found in Redis: {} and begin block is given as {}',
                    last_block_data_redis.decode("utf-8"), begin_block_epoch
                )
                self._logger.debug(
                    'Using redis last epoch block as begin block and ignoring begin block given as {}',
                    begin_block_epoch
                )
            else:
                self._logger.debug('Begin block not given, attempting starting from Redis')

            begin_block_epoch = int(last_block_data_redis.decode("utf-8")) + 1
            self._logger.debug(f'Found last epoch block : {begin_block_epoch} in Redis. Starting from checkpoint.')

        end_block_epoch = self._end
        # Sleep only 1 second to speed up simulation
        if self._simulation_mode:
            sleep_secs_between_chunks = 1
        else:
            sleep_secs_between_chunks = 60
        rpc_obj = ConstructRPC(network_id=settings.chain.chain_id)
        rpc_urls = []
        for node in settings.chain.rpc.nodes:
            self._logger.debug("node {}", node.url)
            rpc_urls.append(node.url)
        rpc_nodes_obj = RPCNodesObject(
            NODES=rpc_urls,
            RETRY_LIMIT=settings.chain.rpc.retry
        )
        generated_block_counter = 0
        self._logger.debug('Starting {}', Process.name)
        while True if not self._simulation_mode else generated_block_counter < 10:
            try:
                cur_block = rpc_obj.rpc_eth_blocknumber(rpc_nodes=rpc_nodes_obj)
            except Exception as ex:
                self._logger.error(
                    "Unable to fetch latest block number due to RPC failure {}. Retrying after {} seconds.",
                    ex,
                    settings.chain.epoch.block_time)
                sleep(settings.chain.epoch.block_time)
                continue
            else:
                self._logger.debug('Got current head of chain: {}', cur_block)
                if not begin_block_epoch:
                    self._logger.debug('Begin of epoch not set')
                    begin_block_epoch = cur_block
                    self._logger.debug('Set begin of epoch to current head of chain: {}', cur_block)
                    self._logger.debug('Sleeping for: {} seconds', settings.chain.epoch.block_time)
                    sleep(settings.chain.epoch.block_time)
                else:
                    # self._logger.debug('Picked begin of epoch: {}', begin_block_epoch)
                    end_block_epoch = cur_block - settings.chain.epoch.head_offset
                    if not (end_block_epoch - begin_block_epoch + 1) >= settings.chain.epoch.height:
                        sleep_factor = settings.chain.epoch.height - ((end_block_epoch - begin_block_epoch) + 1)
                        self._logger.debug('Current head of source chain estimated at block {} after offsetting | '
                                           '{} - {} does not satisfy configured epoch length. '
                                           'Sleeping for {} seconds for {} blocks to accumulate....',
                                           end_block_epoch, begin_block_epoch, end_block_epoch,
                                           sleep_factor * settings.chain.epoch.block_time, sleep_factor
                                           )
                        time.sleep(sleep_factor * settings.chain.epoch.block_time)
                        continue
                    self._logger.debug('Chunking blocks between {} - {} with chunk size: {}', begin_block_epoch,
                                       end_block_epoch, settings.chain.epoch.height)
                    for epoch in chunks(begin_block_epoch, end_block_epoch, settings.chain.epoch.height):
                        if epoch[1] - epoch[0] + 1 < settings.chain.epoch.height:
                            self._logger.debug(
                                'Skipping chunk of blocks {} - {} as minimum epoch size not satisfied | '
                                'Resetting chunking to begin from block {}',
                                epoch[0], epoch[1], epoch[0]
                            )
                            begin_block_epoch = epoch[0]
                            break
                        epoch_block = {'begin': epoch[0], 'end': epoch[1]}
                        generated_block_counter += 1
                        self._logger.debug('Epoch of sufficient length found: {}', epoch_block)

                        await self._writer_redis_pool.set(name=get_epoch_generator_last_epoch(),
                                                          value=epoch_block['end'])
                        await self._writer_redis_pool.zadd(
                            name=get_epoch_generator_epoch_history(),
                            mapping={json.dumps({"begin": epoch_block['begin'], "end": epoch_block['end']}): int(
                                time.time())}
                        )

                        if self._simulation_mode and generated_block_counter >= 10:
                            break

                        epoch_generator_history_len = await self._writer_redis_pool.zcard(
                            get_epoch_generator_epoch_history())

                        # Remove oldest epoch history if length exceeds configured limit
                        history_len = settings.chain.epoch.history_length
                        if epoch_generator_history_len > history_len:
                            await self._writer_redis_pool.zremrangebyrank(get_epoch_generator_epoch_history(), 0,
                                                                          -history_len)

                        self.last_sent_block = epoch_block['end']
                        self._logger.debug('Waiting to push next epoch in {} seconds...', sleep_secs_between_chunks)
                        # fixed wait
                        sleep(sleep_secs_between_chunks)
                    else:
                        begin_block_epoch = end_block_epoch + 1


def main(simulation_mode, **kwargs):
    """Spin up the ticker process in event loop"""
    ticker_process = EpochGenerator(simulation_mode=simulation_mode)
    print('Set sim mode: ', simulation_mode)
    asyncio.get_event_loop().run_until_complete(ticker_process.run(**kwargs))


if __name__ == '__main__':
    args = sys.argv
    kwargs_dict = dict()
    if len(args) > 1:
        end_block = int(args[1])
        kwargs_dict['end'] = end_block
        main(simulation_mode=False, **kwargs_dict)
    else:
        main(simulation_mode=False)
