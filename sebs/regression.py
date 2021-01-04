
import logging
import unittest
import testtools
from typing import Set

from sebs.faas.function import Trigger

benchmarks = [
    "110.dynamic-html",
    "120.uploader",
    "210.thumbnailer",
    #"220.video-processing",
    #"311.compression",
    #"411.image-recognition",
    #"501.graph-pagerank",
    #"502.graph-mst",
    #"503.graph-bfs",
    #"504.dna-visualisation"
]

class TestSequenceMeta(type):

    def __init__(cls, name, bases, attrs, deployment_name, config, experiment_config, triggers):
        type.__init__(cls, name, bases, attrs)
        cls.deployment_name = deployment_name
        cls.config = config
        cls.experiment_config = experiment_config
        cls.triggers = triggers

    def __new__(mcs, name, bases, dict, deployment_name, config, experiment_config, triggers):

        def gen_test(benchmark_name):
            def test(self):
                deployment_client = self.client.get_deployment(
                    self.config,
                    f"regression_test_{deployment_name}_{benchmark_name}.log"
                )
                logging.info(
                    f"Begin regression test of {benchmark_name} on "
                    f"{deployment_client.name()}"
                )
                deployment_client.initialize()
                experiment_config = self.client.get_experiment_config(self.experiment_config)
                benchmark = self.client.get_benchmark(
                    benchmark_name, deployment_client, experiment_config
                )
                storage = deployment_client.get_storage(
                    replace_existing=experiment_config.update_storage
                )
                func = deployment_client.get_function(
                    benchmark,
                    deployment_client.default_function_name(benchmark)
                )
                input_config = benchmark.prepare_input(storage=storage, size="test")

                failure = False
                for trigger_type in triggers:
                    trigger = deployment_client.create_trigger(
                        func, trigger_type
                    )
                    # Synchronous invoke
                    ret = trigger.sync_invoke(input_config)
                    if ret.stats.failure:
                        failure = True
                        deployment_client.logging.error(f"{benchmark_name} fail on trigger: {trigger_type}")
                    else:
                        deployment_client.logging.info(f"{benchmark_name} success on trigger: {trigger_type}")
                    
                if failure:
                    raise RuntimeError(f"Test of {benchmark_name} failed!")
            return test

        for benchmark in benchmarks:
            for trigger in triggers:
                test_name = "test_%s" % benchmark
                dict[test_name] = gen_test(benchmark)
        return type.__new__(mcs, name, bases, dict)

class AWSTestSequence(unittest.TestCase,
        metaclass=TestSequenceMeta,
        deployment_name="aws",
        config = {
            "name": "aws",
            "aws": {
                "region": "us-east-1"
            }
        },
        experiment_config = {
            "update_code": False,
            "update_storage": False,
            "download_results": False,
            "runtime": {
              "language": "python",
              "version": "3.6"
            }
        },
        triggers = [Trigger.TriggerType.LIBRARY, Trigger.TriggerType.HTTP]
    ):
    pass

class AzureTestSequence(unittest.TestCase,
        metaclass=TestSequenceMeta,
        deployment_name="azure",
        config = {
            "name": "azure",
            "azure": {
                "region": "westeurope"
            }
        },
        experiment_config = {
            "update_code": False,
            "update_storage": False,
            "download_results": False,
            "runtime": {
              "language": "python",
              "version": "3.6"
            },
        },
        triggers = [Trigger.TriggerType.HTTP]
    ):
    pass


# https://stackoverflow.com/questions/22484805/a-simple-working-example-for-testtools-concurrentstreamtestsuite
class TracingStreamResult(testtools.StreamResult):
    all_correct: bool
    output = {}

    def __init__(self):
        self.all_correct = True
        self.success = set()
        self.failures = set()

    def status(self, *args, **kwargs):
        self.all_correct = self.all_correct and (kwargs["test_status"] in ["inprogress", "success"])
        test_name = kwargs["test_id"].split('_')[-1]
        if not kwargs["test_status"]:
            test_id = kwargs["test_id"]
            if test_id not in self.output:
                self.output[test_id] = b""
            self.output[test_id] += kwargs["file_bytes"]
        elif kwargs["test_status"] == "fail":
            print('{0[test_id]}: {0[test_status]}'.format(kwargs))
            print('{0[test_id]}: {1}'.format(kwargs, self.output[kwargs["test_id"]].decode()))
            self.failures.add(test_name)
        elif kwargs["test_status"] == "success":
            self.success.add(test_name)

def regression_suite(sebs_client, providers: Set[str]):
    suite = unittest.TestSuite()
    if "aws" in providers:
        suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequence))
    if "azure" in providers:
        suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AzureTestSequence))
    tests = []
    for case in suite:
        for test in case:
            test.client = sebs_client
            tests.append(test)
    concurrent_suite = testtools.ConcurrentStreamTestSuite(lambda: ((test, None) for test in tests))
    result = TracingStreamResult()
    result.startTestRun()
    concurrent_suite.run(result)
    result.stopTestRun()
    print(f"Succesfully executed {len(result.success)} out of {len(tests)} functions")
    for suc in result.success:
        print(f"- {suc}")
    if len(result.failures):
        print(f"Failures when executing {len(result.failures)} out of {len(tests)} functions")
        for failure in result.failures:
            print(f"- {failure}")
    return not result.all_correct
