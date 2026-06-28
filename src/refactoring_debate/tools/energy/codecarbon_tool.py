"""CodeCarbon — estimates the energy consumption and CO2-equivalent emissions of
executing the submitted code (the sustainability/green-smells signal).

Runs the module under an ``OfflineEmissionsTracker`` in an isolated subprocess so
the measurement never contaminates the API process.
"""

from __future__ import annotations

import json

from refactoring_debate.core.metrics import (
    Finding,
    Severity,
    ToolCategory,
    ToolResult,
    ToolStatus,
)
from refactoring_debate.tools.base import (
    PYTHON,
    AnalysisContext,
    DynamicAnalyzer,
    run_subprocess,
)

# Standalone runner: tracks emissions around an isolated run of the target module.
_RUNNER = '''\
import json, runpy, sys
from codecarbon import OfflineEmissionsTracker

target, outfile, iso = sys.argv[1], sys.argv[2], sys.argv[3]
tracker = OfflineEmissionsTracker(
    country_iso_code=iso, save_to_file=False, log_level="error", measure_power_secs=1
)
error = None
tracker.start()
try:
    runpy.run_path(target, run_name="__main__")
except SystemExit:
    pass
except BaseException as exc:  # noqa: BLE001
    error = repr(exc)
finally:
    tracker.stop()

data = tracker.final_emissions_data
result = {
    "emissions_kg": getattr(data, "emissions", None),
    "energy_kwh": getattr(data, "energy_consumed", None),
    "cpu_energy_kwh": getattr(data, "cpu_energy", None),
    "ram_energy_kwh": getattr(data, "ram_energy", None),
    "duration_s": getattr(data, "duration", None),
    "error": error,
}
with open(outfile, "w") as fh:
    json.dump(result, fh)
'''


class CodeCarbonAnalyzer(DynamicAnalyzer):
    name = "codecarbon"
    category = ToolCategory.ENERGY
    country_iso_code = "USA"

    def analyze(self, ctx: AnalysisContext) -> ToolResult:
        runner = ctx.workdir / "_cc_runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        out = ctx.workdir / "codecarbon.json"

        proc = run_subprocess(
            [PYTHON, runner.name, ctx.file_path.name, out.name, self.country_iso_code],
            cwd=ctx.workdir,
            timeout=ctx.settings.dynamic_timeout + 10,
            env=self.clean_env(),
        )
        if proc.timed_out:
            return self._result(
                status=ToolStatus.ERROR,
                summary=f"execution exceeded {ctx.settings.dynamic_timeout}s timeout",
            )
        if not out.exists():
            return self._result(
                status=ToolStatus.ERROR,
                summary="codecarbon produced no measurement",
                error=(proc.stderr or proc.stdout)[:500],
            )

        data = json.loads(out.read_text(encoding="utf-8"))
        energy = float(data.get("energy_kwh") or 0.0)
        emissions = float(data.get("emissions_kg") or 0.0)
        duration = float(data.get("duration_s") or 0.0)

        findings: list[Finding] = []
        # Power draw normalized over runtime — a proxy for energy intensity.
        if duration > 0 and energy > 0:
            avg_watts = (energy * 1000.0) / (duration / 3600.0)
            findings.append(
                Finding(
                    tool=self.name,
                    category=self.category,
                    severity=Severity.INFO,
                    message=(
                        f"Estimated footprint: {energy * 1000:.3f} Wh / "
                        f"{emissions * 1000:.4f} gCO2eq over {duration:.2f}s "
                        f"(~{avg_watts:.1f} W average draw)"
                    ),
                    metric="energy_wh",
                    value=round(energy * 1000, 4),
                    rule="energy-footprint",
                )
            )

        summary = (
            f"{energy * 1000:.3f} Wh, {emissions * 1000:.4f} gCO2eq over {duration:.2f}s"
            if energy > 0
            else "negligible/unmeasurable energy use"
        )
        return ToolResult(
            tool=self.name,
            category=self.category,
            status=ToolStatus.OK,
            summary=summary,
            metrics={
                "energy_wh": round(energy * 1000, 6),
                "emissions_gco2eq": round(emissions * 1000, 6),
                "cpu_energy_wh": round(float(data.get("cpu_energy_kwh") or 0.0) * 1000, 6),
                "ram_energy_wh": round(float(data.get("ram_energy_kwh") or 0.0) * 1000, 6),
                "duration_s": round(duration, 4),
            },
            findings=findings,
        )
