import unittest

from pcslow.diagnosis import DiagnosisEngine
from pcslow.models import DiagnosisType
from pcslow.scenarios import scenario


class DiagnosisEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = DiagnosisEngine()

    def assert_primary(self, scenario_name, expected):
        diagnoses = self.engine.analyze(scenario(scenario_name))
        self.assertEqual(diagnoses[0].diagnosis_type, expected)
        self.assertGreaterEqual(diagnoses[0].confidence, 0.45)
        self.assertTrue(diagnoses[0].evidence)
        return diagnoses[0]

    def test_normal_pc_has_insufficient_evidence(self):
        diagnoses = self.engine.analyze(scenario("normal"))
        self.assertEqual(diagnoses[0].diagnosis_type, DiagnosisType.INSUFFICIENT_EVIDENCE)

    def test_memory_pressure(self):
        diagnosis = self.assert_primary("memory", DiagnosisType.MEMORY_PRESSURE)
        signals = {item.signal for item in diagnosis.evidence}
        self.assertIn("memory_used_percent", signals)
        self.assertIn("memory_available_mb", signals)

    def test_cpu_saturation(self):
        self.assert_primary("cpu", DiagnosisType.CPU_BOTTLENECK)

    def test_disk_saturation(self):
        self.assert_primary("disk", DiagnosisType.DISK_BOTTLENECK)

    def test_background_process(self):
        self.assert_primary("background", DiagnosisType.BACKGROUND_PROCESS)

    def test_low_disk_space(self):
        self.assert_primary("low-disk", DiagnosisType.LOW_DISK_SPACE)

    def test_gpu_heavy(self):
        self.assert_primary("gpu", DiagnosisType.GPU_BOTTLENECK)

    def test_network_latency(self):
        self.assert_primary("network", DiagnosisType.NETWORK_RELATED)

    def test_multiple_bottlenecks_have_alternatives(self):
        diagnoses = self.engine.analyze(scenario("multiple"))
        self.assertGreaterEqual(len(diagnoses), 2)
        self.assertTrue(diagnoses[0].alternatives)

    def test_insufficient_samples(self):
        diagnoses = self.engine.analyze(scenario("insufficient"))
        self.assertEqual(diagnoses[0].diagnosis_type, DiagnosisType.INSUFFICIENT_EVIDENCE)


if __name__ == "__main__":
    unittest.main()
