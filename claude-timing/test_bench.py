import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent

def module():
    path = ROOT / 'bench.py'
    assert path.exists(), 'benchmark implementation is missing'
    spec = importlib.util.spec_from_file_location('bench', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

class EventTests(unittest.TestCase):
    def test_real_event_shapes_and_missing_values(self):
        m = module()
        s = m.Stats()
        s.accept({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'x'}}}, 1.2)
        s.accept({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':'hello'}}}, 2.1)
        s.accept({'type':'assistant','message':{'id':'m1','content':[{'type':'tool_use','id':'t1','name':'Read','input':{}}]}}, 3.0)
        s.accept({'type':'assistant','message':{'id':'m1','content':[{'type':'tool_use','id':'t1','name':'Read','input':{}}]}}, 3.1)
        s.accept({'type':'result','subtype':'success','is_error':False,'duration_ms':4000,'duration_api_ms':3200,'num_turns':2,'usage':{'input_tokens':100,'output_tokens':20},'modelUsage':{'glm-5.3-flash':{}},'result':'done'},4.0)
        r = s.row(4.2, 0, False)
        self.assertEqual(r['status'], 'success')
        self.assertEqual(r['first_model_delta_s'],1.2)
        self.assertEqual(r['first_text_delta_s'],2.1)
        self.assertEqual(r['tool_calls'],1)
        self.assertEqual(r['api_s'],3.2)
        self.assertIsNone(r['cache_read_tokens'])
        self.assertIsNone(r['cost_usd'])
        self.assertEqual(m.Stats().row(1,0,False)['status'],'no_result')
        self.assertEqual(s.row(5,0,True)['status'],'timeout')
        self.assertEqual(s.row(5,1,False)['status'],'process_error')

class SetupTests(unittest.TestCase):
    def test_windows_npm_resolution_and_run_arguments(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = pathlib.Path(tmp)
            shim = root/'claude.cmd'
            shim.write_text('@rem fixture')
            pkg = root/'node_modules'/'@anthropic-ai'/'claude-code'
            pkg.mkdir(parents=True)
            (root/'node.exe').write_text('fixture')
            (pkg/'cli.js').write_text('// fixture')
            (pkg/'package.json').write_text('{"name":"@anthropic-ai/claude-code","bin":{"claude":"cli.js"}}')
            m = module()
            self.assertEqual(m.resolve_claude(str(shim),windows=True),[str(root/'node.exe'),str(pkg/'cli.js')])
            args = m.parser().parse_args(['--repo',str(root),'--model','glm-5.3-flash'])
            base = m.command(['claude'],args,'baseline','Read only.')
            lite = m.command(['claude'],args,'lite','Read only.')
            self.assertEqual(lite[:-2],base)
            self.assertEqual(lite[-2],'--system-prompt-file')
            self.assertNotIn('--dangerously-skip-permissions',base)
            self.assertEqual(m.order(2),['baseline','lite','lite','baseline'])
            (pkg/'package.json').write_text('{"name":"@anthropic-ai/claude-code","bin":{"claude":"../../../outside.js"}}')
            with self.assertRaises(ValueError):
                m.resolve_claude(str(shim),windows=True)

class EndToEndTests(unittest.TestCase):
    def test_cli_writes_metrics_and_keeps_failures(self):
        import tempfile
        import sys
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            p = pathlib.Path(tmp)
            task = p/'task.txt'
            task.write_text('Read only fixture task.', encoding='utf-8')
            fake = p/'fake.py'
            fake.write_text("import sys,json\nif '--version' in sys.argv:\n print('OFFLINE FIXTURE'); sys.exit()\nprint(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','id':'r1','name':'Read'}]}}))\nprint(json.dumps({'type':'result','subtype':'success','is_error':False,'duration_ms':1,'duration_api_ms':1,'num_turns':1,'result':'OFFLINE FIXTURE ONLY','usage':{'input_tokens':10,'output_tokens':2},'modelUsage':{'fixture':{}}}))\n",encoding='utf-8')
            m = module()
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()), patch.object(m,'resolve_claude',return_value=[sys.executable,str(fake)]):
                rc = m.main(['--run','--repo',str(p),'--out',str(p/'out'),'--task-file',str(task),'--pairs','2'])
            self.assertEqual(rc,0)
            import csv
            csv_path = next((p/'out').glob('*/metrics.csv'))
            with csv_path.open(encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows),4)
            self.assertEqual([r['variant'] for r in rows],['baseline','lite','lite','baseline'])
            self.assertTrue(all(r['status']=='success' for r in rows))
            self.assertTrue((csv_path.parent/'summary.txt').exists())
            text = m.summarize([dict(variant='baseline',status='timeout',wall_s=10,pair=1),dict(variant='lite',status='success',wall_s=1,pair=1)])
            self.assertIn('timeout',text)
            self.assertIn('paired_success_count=0',text)
            with patch.object(m,'resolve_claude',side_effect=AssertionError('dry run must not discover CLI')):
                self.assertEqual(m.main(['--repo',str(p),'--task-file',str(task)]),0)

class RunnerTests(unittest.TestCase):
    def test_process_stream_and_timeout(self):
        import tempfile
        import sys
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            p = pathlib.Path(tmp)
            fixture = p / 'fixture.py'
            fixture.write_text("import json,sys,time\nprint(json.dumps({'type':'stream_event','event':{'delta':{'type':'text_delta','text':sys.argv[1]}}}),flush=True)\nprint('warning',file=sys.stderr,flush=True)\ntime.sleep(0.03)\nprint(json.dumps({'type':'result','subtype':'success','is_error':False,'result':sys.argv[1],'usage':{'output_tokens':1}}),flush=True)\n",encoding='utf-8')
            m = module()
            row, result = m.run_process([sys.executable,str(fixture),'한글 & \"x\"\nnext'],p,p/'normal',5)
            self.assertEqual(row['status'],'success')
            self.assertEqual(result['result'],'한글 & \"x\"\nnext')
            self.assertIsNotNone(row['first_text_delta_s'])
            self.assertGreater(row['wall_s'],row['first_text_delta_s'])
            self.assertIn('warning',(p/'normal.stderr.log').read_text())
            row, _ = m.run_process([sys.executable,'-c','import time; time.sleep(10)'],p,p/'timeout',0.15)
            self.assertEqual(row['status'],'timeout')
            self.assertLess(row['wall_s'],4)

if __name__ == '__main__':
    unittest.main()
