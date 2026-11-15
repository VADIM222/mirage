import json
import threading

import pytest

from mirage.emulators import CommandError, parse_bs_config
from mirage.model import Instance, Power, Provider
from mirage.preparation import prepare


def test_preparation_preserves_higher_cpu_and_device_identity(tmp_path, monkeypatch):
    config = tmp_path / "vms" / "config" / "leidian1.config"
    config.parent.mkdir(parents=True)
    original = {"advancedSettings.cpuCount": 4, "basicSettings.rootMode": False,
                "propertySettings.phoneAndroidId": "0123456789abcdef", "advancedSettings.memorySize": 4096,
                "advancedSettings.resolution":{"width":960,"height":540},"advancedSettings.resolutionDpi":160}
    config.write_text(json.dumps(original), encoding="utf-8")
    instance = Instance("ld:test:1", Provider.LDPLAYER, "1", "Farm", str(tmp_path), "adb", "127.0.0.1:5557", Power.OFF, cpus=4)
    calls = []
    def run(arguments, **kwargs):
        calls.append(arguments)
        value = json.loads(config.read_text())
        value["basicSettings.rootMode"] = True
        config.write_text(json.dumps(value))
        return ""
    monkeypatch.setattr("mirage.preparation.run", run)
    prepare(instance, tmp_path / "backups", threading.Event())
    assert len(calls) == 1
    assert "--cpu" not in calls[0]
    updated = json.loads(config.read_text())
    assert updated["advancedSettings.cpuCount"] == 4
    assert updated["propertySettings.phoneAndroidId"] == original["propertySettings.phoneAndroidId"]
    assert updated["advancedSettings.memorySize"] == 4096
    assert json.loads(next((tmp_path / "backups").iterdir()).read_text()) == original


def test_preparation_raises_1536_mb_to_two_gb(tmp_path, monkeypatch):
    config = tmp_path / "vms" / "config" / "leidian1.config"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"advancedSettings.cpuCount":2, "basicSettings.rootMode":True,
                                 "advancedSettings.memorySize":1536,"advancedSettings.resolution":{"width":960,"height":540},
                                 "advancedSettings.resolutionDpi":160}))
    instance = Instance("ld:test:1", Provider.LDPLAYER, "1", "Farm", str(tmp_path), "adb", "127.0.0.1:5557", Power.OFF)
    def run(arguments, **kwargs):
        value = json.loads(config.read_text())
        value["advancedSettings.memorySize"] = int(arguments[arguments.index("--memory") + 1])
        config.write_text(json.dumps(value))
        return ""
    monkeypatch.setattr("mirage.preparation.run", run)
    prepare(instance, tmp_path / "backups", threading.Event())
    assert json.loads(config.read_text())["advancedSettings.memorySize"] == 2048


def bluestacks(tmp_path,monkeypatch,*,cpus=1,memory=1536,bom=True):
    monkeypatch.setenv("ProgramData",str(tmp_path))
    config=tmp_path/"BlueStacks_nxt"/"bluestacks.conf"
    config.parent.mkdir()
    text='\r\n'.join(('bst.enable_adb_access="0"','bst.feature.rooting="0"',
        'bst.enable_adb_remote_access="0"','bst.instance.Pie64.display_name="Farm"',
        f'bst.instance.Pie64.cpus="{cpus}"',f'bst.instance.Pie64.ram="{memory}"',
        'bst.instance.Pie64.enable_root_access="0"','bst.instance.Pie64.android_id="0123456789abcdef"',
        'bst.instance.Pie64.fb_width="1920"','bst.instance.Pie64.fb_height="1080"','bst.instance.Pie64.dpi="240"',
        'bst.instance.Nougat64.cpus="6"','bst.instance.Nougat64.ram="8192"',
        'bst.instance.Nougat64.enable_root_access="0"',''))
    config.write_bytes((b'\xef\xbb\xbf' if bom else b'')+text.encode('utf8'))
    instance=Instance("bs:test:Pie64",Provider.BLUESTACKS,"Pie64","Farm",str(tmp_path),"adb",
                      "127.0.0.1:5555",Power.OFF)
    monkeypatch.setattr("mirage.preparation.run",lambda *args,**kwargs:"")
    return instance,config


@pytest.mark.parametrize("cpus,memory,bom",[(1,1536,True),(4,4096,False)])
def test_bluestacks_preparation_preserves_other_instances_identity_and_encoding(tmp_path,monkeypatch,cpus,memory,bom):
    instance,config=bluestacks(tmp_path,monkeypatch,cpus=cpus,memory=memory,bom=bom)
    original=config.read_bytes()
    prepare(instance,tmp_path/"backups",threading.Event())
    updated=config.read_bytes()
    settings=parse_bs_config(updated.decode('utf-8-sig'))
    assert settings['bst.instance.Pie64.cpus']==str(max(2,cpus))
    assert settings['bst.instance.Pie64.ram']==str(max(2048,memory))
    assert settings['bst.instance.Pie64.enable_root_access']=='1'
    assert settings['bst.instance.Pie64.fb_width']=='960' and settings['bst.instance.Pie64.fb_height']=='540'
    assert settings['bst.instance.Pie64.dpi']=='160'
    assert settings['bst.feature.rooting']==settings['bst.enable_adb_access']=='1'
    assert settings['bst.enable_adb_remote_access']=='0'
    assert settings['bst.instance.Pie64.android_id']=='0123456789abcdef'
    assert settings['bst.instance.Nougat64.cpus']=='6' and settings['bst.instance.Nougat64.ram']=='8192'
    assert settings['bst.instance.Nougat64.enable_root_access']=='0'
    assert updated.startswith(b'\xef\xbb\xbf')==bom
    assert b'\r\n' in updated and b'\n' not in updated.replace(b'\r\n',b'')
    assert next((tmp_path/'backups').iterdir()).read_bytes()==original
    assert not list(config.parent.glob('.mirage-*'))


def test_ldplayer_preparation_sets_the_verified_adapter_resolution(tmp_path,monkeypatch):
    config=tmp_path/'vms'/'config'/'leidian2.config'
    config.parent.mkdir(parents=True)
    original={'advancedSettings.cpuCount':2,'advancedSettings.memorySize':2048,'basicSettings.rootMode':True,
        'advancedSettings.resolution':{'width':1920,'height':1080},'advancedSettings.resolutionDpi':240,
        'propertySettings.phoneAndroidId':'1234567890abcdef'}
    config.write_text(json.dumps(original))
    instance=Instance('ld:test:2',Provider.LDPLAYER,'2','Farm',str(tmp_path),'adb','127.0.0.1:5559',Power.OFF)
    def run(arguments,**kwargs):
        assert arguments[arguments.index('--resolution')+1]=='960,540,160'
        updated={**original,'advancedSettings.resolution':{'width':960,'height':540},'advancedSettings.resolutionDpi':160}
        config.write_text(json.dumps(updated))
    monkeypatch.setattr('mirage.preparation.run',run)
    prepare(instance,tmp_path/'backups',threading.Event())
    updated=json.loads(config.read_text())
    assert updated['advancedSettings.resolution']=={'width':960,'height':540}
    assert updated['propertySettings.phoneAndroidId']==original['propertySettings.phoneAndroidId']
    assert json.loads(next((tmp_path/'backups').iterdir()).read_text())==original


def test_running_bluestacks_is_closed_configured_and_reopened(tmp_path,monkeypatch):
    instance,config=bluestacks(tmp_path,monkeypatch)
    state={"online":True}
    calls=[]
    monkeypatch.setattr('mirage.preparation.run',lambda *args,**kwargs:
        '"Pie64" {11111111-1111-1111-1111-111111111111}' if state['online'] else '')
    def close(value):
        assert value==instance
        assert parse_bs_config(config.read_text(encoding='utf-8-sig'))['bst.instance.Pie64.enable_root_access']=='0'
        state['online']=False;calls.append('close')
    def launch(value):
        assert value==instance
        assert parse_bs_config(config.read_text(encoding='utf-8-sig'))['bst.instance.Pie64.enable_root_access']=='1'
        calls.append('launch')
    monkeypatch.setattr('mirage.preparation.close',close)
    monkeypatch.setattr('mirage.preparation.launch',launch)
    prepare(instance,tmp_path/'backups',threading.Event())
    assert calls==['close','launch']


@pytest.mark.parametrize('failure',['other_running','unknown_list','changed_file','cancel','duplicate','missing','identity','replace'])
def test_bluestacks_aborts_before_any_unconfirmed_config_change(tmp_path,monkeypatch,failure):
    instance,config=bluestacks(tmp_path,monkeypatch)
    cancelled=threading.Event()
    if failure=='duplicate':config.write_bytes(config.read_bytes()+b'bst.feature.rooting="0"\r\n')
    if failure=='missing':config.write_bytes(config.read_bytes().replace(b'bst.feature.rooting="0"\r\n',b''))
    if failure=='identity':config.write_bytes(config.read_bytes().replace(b'display_name="Farm"',b'display_name="Other"'))
    original=config.read_bytes()
    count=[]
    def run(*args,**kwargs):
        count.append(True)
        if failure=='other_running':return '"Nougat64" {11111111-1111-1111-1111-111111111111}'
        if failure=='unknown_list':return 'Service unavailable'
        if len(count)==3:
            if failure=='changed_file':config.write_bytes(original+b'bst.external="edit"\r\n')
        return ''
    monkeypatch.setattr('mirage.preparation.run',run)
    monkeypatch.setattr('mirage.preparation.close',lambda i:pytest.fail('Unexpected close'))
    monkeypatch.setattr('mirage.preparation.launch',lambda i:pytest.fail('Unexpected launch'))
    if failure=='cancel':
        import mirage.preparation as preparation
        real_copy=preparation.shutil.copystat
        def copy(*args,**kwargs):real_copy(*args,**kwargs);cancelled.set()
        monkeypatch.setattr('mirage.preparation.shutil.copystat',copy)
    if failure=='replace':
        def replace(*args):raise PermissionError('File is in use')
        monkeypatch.setattr('mirage.preparation.os.replace',replace)
    with pytest.raises((CommandError,PermissionError)):
        prepare(instance,tmp_path/'backups',cancelled)
    assert config.read_bytes()==original+(b'bst.external="edit"\r\n' if failure=='changed_file' else b'')
    assert not list(config.parent.glob('.mirage-*'))
