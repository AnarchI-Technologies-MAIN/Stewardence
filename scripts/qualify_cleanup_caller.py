"""Exercise exact restored-request runner with two uncertain create outcomes."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import qualify_restored_report_access as runner

original_root = runner.ROOT
outcomes = []
for scenario in ['absent', 'owned', 'foreign', 'missing-label', 'inspect-error', 'replaced']:
    created_before_failure = scenario != 'absent'
    with tempfile.TemporaryDirectory(prefix='stewardence-cleanup-caller-') as temporary:
        root = Path(temporary)
        (root/'scripts').mkdir()
        (root/'scripts/restored_report_access_probe.py').write_bytes(
            (original_root/'scripts/restored_report_access_probe.py').read_bytes())
        runner.ROOT = root
        fixtures = [('OBJECT_RECEIPT', {'restore_passed':True,'cleanup_passed':True,'postgres_image_id':'sha256:postgres'}),
                    ('DATABASE_RECEIPT', {'private_key_file':str(root/'unused-key')}),
                    ('IMAGE_RECEIPT', {'exit_code':0,'image_id':'sha256:candidate'})]
        for attribute, value in fixtures:
            path = root/(attribute+'.json')
            path.write_text(json.dumps(value))
            setattr(runner, attribute, path)
        calls, state = [], {'network':None, 'id':'a'*64}
        def fake_docker(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('image','inspect'):
                return SimpleNamespace(stdout=args[-1])
            if args[:2] == ('network','create'):
                state['network'] = args[-1] if created_before_failure else None
                raise RuntimeError('Injected uncertain creation')
            if args[:2] == ('network','rm'):
                assert args[-1] == 'a'*64
                if state['id'] != args[-1]:
                    raise RuntimeError('Inspected network no longer exists')
                state['network'] = None
            if args[:2] == ('network','inspect'):
                assert args[-1] == 'a'*64
                if scenario == 'inspect-error':
                    raise RuntimeError('Injected inspection failure')
                label = state['network'] if scenario != 'foreign' else 'another-run'
                labels = {} if scenario == 'missing-label' else {'stewardence.qualification-run':label}
                record = {'Name':state['network'],'Id':'a'*64,'Labels':labels}
                if scenario == 'replaced':
                    state['id'] = 'b'*64
                return SimpleNamespace(stdout=json.dumps(record))
            if args[:3] == ('network','ls','-q'):
                return SimpleNamespace(stdout=state['id'] if state['network'] else '')
            return SimpleNamespace(stdout='')
        runner.docker = fake_docker
        try:
            runner.main()
            raise AssertionError('Creation failure was swallowed')
        except RuntimeError as error:
            assert str(error) == ('Injected uncertain creation' if scenario in ['absent','owned'] else 'Isolated request cleanup incomplete; overall qualification withheld')
        assert sum(call[:3] == ('network','ls','-q') for call in calls) == 2
        assert sum(call[:2] == ('network','rm') for call in calls) == int(scenario in ['owned','replaced'])
        assert (state['network'] is None) == (scenario in ['absent','owned'])
        assert not list(root.rglob('qualification-summary.json'))
        outcomes.append({'scenario':scenario,'network_reconciled':True,
                         'owned_or_absent_target_cleaned':scenario in ['absent','owned'],
                         'uncertain_or_foreign_target_preserved':scenario not in ['absent','owned'],
                         'overall_pass_withheld':True})
receipt = {'qualification_passed':True,'exact_runner_main_executed':True,
           'io_mocked':True,'real_resources_created':False,'cases':outcomes}
(original_root/'evidence/cleanup-caller-qualification.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
