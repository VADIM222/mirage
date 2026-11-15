from pathlib import Path
import os
import sys
import time

import pytest

from mirage.emulators import CommandError, bs_instances, parse_bs_config, parse_ld_list, run
from mirage.model import Power


def test_bluestacks_uses_live_port_and_stable_id_after_rename():
    text = ('bst.instance.Pie64.display_name="My Farm"\n'
            'bst.instance.Pie64.adb_port="5555"\n'
            'bst.instance.Pie64.status.adb_port="5585"\n'
            'bst.instance.Pie64.cpus="2"\n')
    config = parse_bs_config(text)
    first = bs_instances(config, Path("C:/BS"), {"Pie64"})[0]
    config["bst.instance.Pie64.display_name"] = "Renamed"
    second = bs_instances(config, Path("C:/BS"), set())[0]
    assert first.id == second.id
    assert first.serial == "127.0.0.1:5585"
    assert first.power == Power.ONLINE
    assert second.power == Power.OFF


def test_ld_names_with_commas_and_boot_status():
    text = "1,Farm, East,1,2,1,123,456,960,540,160\n2,Other,1,2,0,124,457,960,540,160"
    first, second = parse_ld_list(text, Path("C:/LD"))
    assert first.name == "Farm, East"
    assert first.key == "1"
    assert first.power == Power.ONLINE
    assert second.power == Power.BOOTING


def test_legacy_ld_output_and_bad_lines():
    result = parse_ld_list("garbage\n0,Old Farm,0,0,0,-1,-1\n", Path("C:/LD"))
    assert len(result) == 1
    assert result[0].power == Power.OFF


@pytest.mark.skipif(os.name != "nt", reason="Windows vendor process trees")
def test_command_timeout_also_bounds_child_holding_output_pipe():
    source = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(30)"
    before = time.monotonic()
    with pytest.raises(CommandError, match="превысила"):
        run([sys.executable, "-c", source], timeout=0.3)
    assert time.monotonic() - before < 5
