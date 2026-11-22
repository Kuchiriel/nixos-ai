import json
import pathlib
import py_compile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
KERNEL = ROOT / "benchmarks/littlebit2/kaggle-official"


class LittleBit2OfficialKernelContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((KERNEL / "contract.json").read_text(encoding="utf-8"))
        self.metadata = json.loads((KERNEL / "kernel-metadata.json").read_text(encoding="utf-8"))

    def test_contract_pins_official_paired_protocol(self):
        contract = self.contract
        protocol = contract["protocol"]
        self.assertEqual("42d658b0c79f76450b34b6a3547462c7cdc3e1a0", contract["official_commit"])
        self.assertEqual("official main.py", protocol["trainer"])
        self.assertEqual(5.0, protocol["epochs"])
        self.assertTrue(protocol["residual"])
        self.assertEqual(10.0, protocol["l2l_loss_scale"])
        self.assertEqual(4, protocol["effective_global_batch_size"])
        self.assertEqual(
            [("baseline", False), ("littlebit2", True)],
            [(row["name"], row["use_itq"]) for row in contract["variants"]],
        )
        self.assertFalse(contract["production_writes"])

    def test_step_estimate_matches_distributed_measurement(self):
        protocol = self.contract["protocol"]
        resources = self.contract["resources"]
        examples = protocol["expected_dataset_examples"]
        per_rank_batches = (
            examples + resources["minimum_gpu_count"] - 1
        ) // resources["minimum_gpu_count"]
        steps_per_epoch = (
            per_rank_batches + protocol["gradient_accumulation_steps"] - 1
        ) // protocol["gradient_accumulation_steps"]
        self.assertEqual(
            protocol["expected_optimizer_steps_per_variant"],
            steps_per_epoch * int(protocol["epochs"]),
        )

    def test_kernel_metadata_and_script_are_executable_contract(self):
        self.assertEqual("script.py", self.metadata["code_file"])
        self.assertEqual("NvidiaTeslaT4", self.metadata["machine_shape"])
        self.assertTrue(self.metadata["enable_gpu"])
        self.assertTrue(self.metadata["is_private"])
        script = (KERNEL / "script.py").read_text(encoding="utf-8")
        self.assertIn('"main.py"', script)
        self.assertIn('"eval.py"', script)
        self.assertNotIn("minimal_qat.py --use-itq", script)
        py_compile.compile(str(KERNEL / "script.py"), doraise=True)


if __name__ == "__main__":
    unittest.main()
