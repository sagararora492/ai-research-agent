from __future__ import annotations
import io
import json
import tempfile
import threading
import time
import unittest
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch
from agentic_research_assistant.cli import main
from agentic_research_assistant.config import build_orchestrator
from agentic_research_assistant.harness import AgentHarness, HarnessConfig
from agentic_research_assistant.llm import ModelProfile, StructuredModel
from agentic_research_assistant.providers import LocalSearchProvider, ProviderError, SearchResult
from agentic_research_assistant.synthesizer import validate_citations
from agentic_research_assistant.web import run_research

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [{'title':'Evidence', 'url':'https://example.com/evidence', 'content':'Research requires evidence. Research cost and security need evaluation.'}]

def config():
    data = json.loads((ROOT/'examples/agents-mixed.json').read_text())
    data['planner_model'] = data['synthesizer_model'] = None
    return data

class FakeModel:
    def __init__(self, profile, calls, lock):
        self.profile, self.calls, self.lock, self.usage = profile, calls, lock, {}
    def complete(self, instructions, data, schema, name):
        with self.lock: self.calls.append((self.profile.model, name, deepcopy(data)))
        self.usage = {'input_tokens':100, 'output_tokens':20}
        if name == 'research_plan':
            return {'tasks':[{'agent_id':a['id'], 'objective':'Investigate research evidence.', 'evidence_to_collect':[a['focus']]} for a in data['agents']]}
        return {'findings':[{'task_title':t['title'], 'insight':'Research requires evidence.', 'confidence':'low', 'evidence_gaps':['Needs review'], 'citations':[{'source_id':s['id'], 'excerpt':'Research requires evidence.'} for s in data['evidence'] if t['title'] in s['tasks']][:1]} for t in data['tasks']]}

class HarnessTests(unittest.TestCase):
    def build(self, data, provider=None, model_factory=None):
        calls, lock = [], threading.Lock()
        factory = model_factory or (lambda p: FakeModel(p, calls, lock))
        orchestrator = build_orchestrator('local', DOCUMENTS)
        orchestrator.harness = AgentHarness(HarnessConfig.parse(data), provider or orchestrator.researcher.provider, backend_factory=factory)
        return orchestrator, calls

    def test_ten_agents_route_to_three_models_and_merge_citations(self):
        orchestrator, calls = self.build(config())
        with tempfile.TemporaryDirectory() as directory:
            report = orchestrator.run('Research', storage_root=Path(directory))
            manifest = json.loads(Path(report.stored_session.manifest_path).read_text())
        self.assertEqual(Counter(c[0] for c in calls), {'YOUR_OPENAI_MODEL_ID':4, 'YOUR_ANTHROPIC_MODEL_ID':3, 'YOUR_GEMINI_MODEL_ID':3})
        self.assertEqual((len(report.tasks),len(report.findings),len(report.sources),len(report.agent_runs)), (10,10,1,12))
        self.assertEqual(len({f.agent_id for f in report.findings}),10)
        validate_citations(report.findings,report.sources)
        self.assertEqual(manifest['schema_version'],2)
        self.assertEqual(len(manifest['agent_runs']),12)
        self.assertEqual(sum(r.usage.get('output_tokens',0) for r in report.agent_runs),200)
        self.assertEqual(manifest['agent_config'],report.agent_config)

    def test_planner_and_synthesizer_independent_assignments(self):
        data=config(); data['planner_model']='model-c'; data['synthesizer_model']='model-b'
        orchestrator,calls=self.build(data); report=orchestrator.run('Research',persist=False)
        self.assertEqual(calls[0][:2],('YOUR_GEMINI_MODEL_ID','research_plan'))
        self.assertEqual(calls[-1][0],'YOUR_ANTHROPIC_MODEL_ID')
        self.assertEqual(len(calls[-1][2]['prior_findings']),10)
        self.assertEqual(report.agent_runs[-1].status,'completed')
        self.assertTrue(all(t.objective=='Investigate research evidence.' for t in report.tasks))
        validate_citations(report.findings,report.sources)

    def test_bounded_concurrency_and_search_budget(self):
        data=config(); data['max_concurrency']=3; data['max_searches']=13
        class Search:
            active=peak=calls=0
            lock=threading.Lock()
            def search(self,query,limit):
                with self.lock:
                    self.active+=1; self.calls+=1; self.peak=max(self.peak,self.active)
                time.sleep(.01)
                with self.lock: self.active-=1
                return []
        provider=Search(); orchestrator,calls=self.build(data,provider)
        report=orchestrator.run('Research',persist=False)
        self.assertEqual(provider.calls,13); self.assertLessEqual(provider.peak,3); self.assertGreater(provider.peak,1)
        self.assertEqual(calls,[])
        self.assertTrue(all(r.status=='no_evidence' for r in report.agent_runs[1:-1]))

    def test_failed_worker_keeps_other_results_and_fail_policy(self):
        data=config()
        def factory(profile):
            backend=FakeModel(profile,[],threading.Lock())
            if profile.provider=='anthropic': backend.complete=Mock(side_effect=ProviderError('Model unavailable.'))
            return backend
        orchestrator,_=self.build(data,model_factory=factory); report=orchestrator.run('Research',persist=False)
        self.assertEqual(Counter(r.status for r in report.agent_runs[1:-1]),{'completed':7,'fallback':3})
        self.assertEqual(len(report.warnings),3); validate_citations(report.findings,report.sources)
        data['on_error']='fail'; orchestrator,_=self.build(data,model_factory=factory)
        with self.assertRaises(ProviderError): orchestrator.run('Research',persist=False)

    def test_invalid_planner_and_findings_fallback(self):
        data=config(); data['planner_model']='model-a'
        def factory(profile):
            backend=FakeModel(profile,[],threading.Lock()); backend.complete=Mock(return_value={'tasks':[],'findings':[]}); return backend
        orchestrator,_=self.build(data,model_factory=factory); report=orchestrator.run('Research',persist=False)
        self.assertTrue(all(r.status=='fallback' for r in report.agent_runs[:-1]))
        validate_citations(report.findings,report.sources)

    def test_same_url_different_content_preserves_quotes(self):
        data=json.loads((ROOT/'examples/agents-offline.json').read_text())
        class Search:
            def search(self,query,limit): return [SearchResult('Source','https://example.com/same',query)]
        orchestrator,_=self.build(data,Search()); report=orchestrator.run('Research',persist=False)
        self.assertEqual(len(report.sources),10); validate_citations(report.findings,report.sources)
        for run in report.agent_runs[1:-1]: validate_citations(run.findings,report.sources)

    def test_config_validation_inheritance_and_roundtrip(self):
        data=config(); data['default_model']='model-a'; del data['research_agents'][0]['model']
        parsed=HarnessConfig.parse(data); self.assertEqual(parsed.research_agents[0].model,'model-a')
        self.assertEqual(HarnessConfig.parse(asdict(parsed)),parsed)
        invalid=[None,[],{**data,'max_concurrency':True},{**data,'max_searches':9},{**data,'default_model':'missing'},{**data,'on_error':'ignore'},{**data,'research_agents':[]},{**data,'api_key':'secret'}]
        duplicate=deepcopy(data); duplicate['research_agents'][1]['id']=duplicate['research_agents'][0]['id']; invalid.append(duplicate)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError): HarnessConfig.parse(value)

    def test_arbitrary_team_size_and_profile_count(self):
        data = config()
        data['models'] = {f'model-{i}': {'provider':'openai', 'model':f'custom-{i}'} for i in range(31)}
        data['research_agents'] = [{'id':f'agent-{i}', 'focus':'Evidence', 'model':f'model-{i % 31}'} for i in range(125)]
        data['max_searches'] = 250
        data['max_concurrency'] = 12
        parsed = HarnessConfig.parse(data)
        self.assertEqual(len(parsed.research_agents),125)
        self.assertEqual(len(parsed.models),31)

    def test_web_rejects_model_connection_overrides(self):
        with self.assertRaisesRegex(ValueError, 'configured locally'):
            run_research({'topic':'Research','provider':'local','documents':DOCUMENTS,'agent_config':config()})

    def test_missing_credentials_fail_before_search(self):
        with patch.dict('os.environ',{},clear=True), patch.object(LocalSearchProvider,'search') as search:
            with self.assertRaisesRegex(ValueError,'OPENAI_API_KEY'): build_orchestrator('local',DOCUMENTS,agent_config=config())
            search.assert_not_called()

    def test_offline_team_cli_and_web(self):
        path=ROOT/'examples/agents-offline.json'; data=json.loads(path.read_text()); data.pop('models')
        with patch.dict('os.environ',{},clear=True):
            result=run_research({'topic':'Research','provider':'local','documents':DOCUMENTS,'agent_config':data,'persist':False})
        self.assertEqual(len(result['agent_runs']),12); self.assertIsNone(result['stored_session'])
        stdout=io.StringIO()
        with redirect_stdout(stdout):
            code=main(['Research','--provider','local','--documents',str(ROOT/'examples/documents.json'),'--agent-config',str(path),'--no-persist','--format','json'])
        self.assertEqual(code,0); self.assertEqual(len(json.loads(stdout.getvalue())['tasks']),10)

class ModelAdapterTests(unittest.TestCase):
    def profile(self,provider): return ModelProfile.parse({'provider':provider,'model':'test-model'})
    def test_all_provider_requests_responses_and_usage(self):
        payloads={
            'openai':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}],'usage':{'input_tokens':8,'output_tokens':2}},
            'anthropic':{'stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}],'usage':{'input_tokens':8,'output_tokens':2}},
            'gemini':{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}],'usageMetadata':{'promptTokenCount':8,'candidatesTokenCount':2}},
            'openai_compatible':{'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'prompt_tokens':8,'completion_tokens':2}}}
        for provider,payload in payloads.items():
            with self.subTest(provider=provider):
                client=Mock(); client.post.return_value=payload
                backend=StructuredModel(self.profile(provider),'secret',client,'http://localhost:11434/v1')
                self.assertEqual(backend.complete('instruction',{}, {'type':'object'},'test'),{'ok':True})
                self.assertEqual(backend.usage,{'input_tokens':8,'output_tokens':2})
                args,kwargs=client.post.call_args
                if provider=='anthropic': self.assertEqual(kwargs['headers']['x-api-key'],'secret')
                if provider=='gemini': self.assertNotIn('secret',args[0])
                if provider=='openai_compatible': self.assertTrue(args[0].endswith('/v1/chat/completions'))
                self.assertNotIn('secret',repr(backend))

    def test_refused_truncated_and_malformed_outputs(self):
        for provider,payload in [('openai',{'status':'incomplete'}),('anthropic',{'stop_reason':'max_tokens'}),('gemini',{'candidates':[]}),('openai_compatible',{'choices':[{'finish_reason':'length'}]})]:
            client=Mock(); client.post.return_value=payload
            with self.subTest(provider=provider), self.assertRaises(ProviderError): StructuredModel(self.profile(provider),'key',client).complete('instructions',{}, {},'test')

    def test_compatible_endpoint_validation(self):
        profile=self.profile('openai_compatible')
        with patch.dict('os.environ',{'OPENAI_COMPATIBLE_BASE_URL':'http://127.0.0.1:11434/v1'},clear=True):
            model=StructuredModel.from_profile(profile); self.assertEqual(model.api_key,''); self.assertEqual(model.base_url,'http://127.0.0.1:11434/v1')
        for url in ('http://remote.example/v1','https://user:password@remote.example/v1','https://remote.example/v1?key=secret'):
            with patch.dict('os.environ',{'OPENAI_COMPATIBLE_BASE_URL':url},clear=True), self.assertRaises(ValueError): StructuredModel.from_profile(profile)

    def test_profiles_reject_secrets_and_invalid_limits(self):
        for options in ({'api_key':'secret'},{'provider':'other'},{'model':''},{'max_output_tokens':True},{'base_url_env':'https://example.com'},{'api_key_env':'HOME'},{'max_output_tokens':100000}):
            with self.subTest(options=options), self.assertRaises(ValueError): ModelProfile.parse({'provider':'openai','model':'test',**options})
