import base64, json, unittest
from quotaflow.github_api import GitHub,GitHubError
from quotaflow.models import Account
from .test_models import A

WORKER='''# QUOTAFLOW_WORKER_V1\nname: Worker\nrun-name: QuotaFlow ${{ inputs.job_id }}\non:\n  workflow_dispatch:\n    inputs:\n      profile: {type: choice}\nrun: ${{ inputs.profile }}\n'''

def fake_api(login='alpha',public=False,valid=True,fail_dispatch=False):
    events=[]
    def fn(req):
        url=req.full_url;events.append((req.get_method(),url))
        if url.endswith('/user'):
            body={'login':login}
        elif '/actions/workflows/worker.yml/runs?' in url:
            body={'workflow_runs':[{'display_title':'QuotaFlow task1','head_branch':'main','status':'completed','conclusion':'success','id':123}]}
        elif '/contents/.github/workflows/' in url:
            body={'encoding':'base64','content':base64.b64encode((WORKER if valid else 'unsafe').encode()).decode()}
        elif '/actions/workflows/worker.yml/dispatches' in url:
            if fail_dispatch:raise GitHubError('simulated timeout')
            return 204,b''
        elif '/actions/workflows/worker.yml' in url:
            body={'name':'Worker','state':'active'}
        elif '/repos/alpha/worker' in url:
            body={'full_name':'alpha/worker','owner':{'login':'alpha'},'archived':False,'private':not public}
        else: raise AssertionError(url)
        return 200,json.dumps(body).encode()
    return fn,events

class GitHubTests(unittest.TestCase):
    def get_client(self,**kw):
        f,events=fake_api(**kw)
        return GitHub(Account.parse(A),transport=f,environ={'GH_ALPHA_TOKEN':'mock-secret'}),events
    def test_verify_owner(self):
        client,_=self.get_client();self.assertEqual(client.verify()['owner'],'alpha')
    def test_wrong_identity(self):
        client,_=self.get_client(login='wrong')
        with self.assertRaises(GitHubError):client.verify()
    def test_missing_worker_contract(self):
        client,_=self.get_client(valid=False)
        with self.assertRaises(GitHubError):client.verify()
    def test_dispatch_only_allowed_profile(self):
        client,_=self.get_client()
        with self.assertRaises(GitHubError):client.dispatch('task1','arbitrary_shell')
    def test_dispatch_does_not_echo_token(self):
        client,events=self.get_client()
        self.assertIsNone(client.dispatch('task1','unit'))
        self.assertTrue(any('/dispatches' in e[1] for e in events))
        self.assertNotIn('mock-secret',str(events))
    def test_find_run_correlated(self):
        client,_=self.get_client();self.assertEqual(client.find_run('task1')['id'],123)
        self.assertIsNone(client.find_run('other'))
    def test_no_token(self):
        with self.assertRaisesRegex(GitHubError,'Missing token'): GitHub(Account.parse(A),environ={})
    def test_public_contract_requires_verified_public_repo(self):
        value={**A,'public_standard_runner':True}
        client=GitHub(Account.parse(value),transport=fake_api(public=False)[0],environ={'GH_ALPHA_TOKEN':'x'})
        with self.assertRaises(GitHubError):client.verify()
        client2=GitHub(Account.parse(value),transport=fake_api(public=True)[0],environ={'GH_ALPHA_TOKEN':'x'})
        self.assertFalse(client2.verify()['private'])
