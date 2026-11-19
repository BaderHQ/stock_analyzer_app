from datetime import datetime,timedelta,timezone
from unittest import TestCase
from brx_obx.engine import BiasEngine,Evidence,WEIGHTS,Bar,confirmed_pivots,volume_percentile,evaluate_reversal
from brx_obx.contracts import Contract,Scenario,ContractPolicy,select_contracts,moneyness
UTC=timezone.utc
T=datetime(2026,11,19,15,0,tzinfo=UTC)

def facts(tf,sign,time=T): return {k:Evidence(sign,time,k) for k in WEIGHTS[tf]}

def contract(**changes):
    args=dict(contract_id='SPY_C_600',kind='CALL',strike=600,spot=601,bid=4.9,ask=5.1,
              quote_time=T-timedelta(seconds=1),last_trade_time=T+timedelta(hours=4),days_to_expiry=7,
              delta=.55,gamma=.04,theta=-.2,vega=.1,iv=.23,settlement='PM')
    args.update(changes);return Contract(**args)

def scenarios(id='SPY_C_600'):return {id:{'base':Scenario('base',6.2,45,.004,-.5),'adverse':Scenario('adverse',3.2,45,-.004,1.0)}}

class BiasTests(TestCase):
    def test_all_weights_100(self): self.assertTrue(all(sum(w.values())==100 for w in WEIGHTS.values()))
    def test_independent_timeframes(self):
        engine=BiasEngine();m=engine.evaluate('SPY','monthly',facts('monthly',-1),T,closed=True)
        d=engine.evaluate('SPY','daily',facts('daily',+1),T,closed=True)
        self.assertEqual((m.confirmed_bias,d.confirmed_bias),('PUT','CALL'))
    def test_coverage(self):
        e=BiasEngine(); r=e.evaluate('SPY','5m',{'structure':Evidence(1,T)},T,closed=True)
        self.assertEqual((r.status,r.confirmed_bias),('INSUFFICIENT_DATA','NEUTRAL'))
    def test_future_data(self):
        with self.assertRaises(ValueError):BiasEngine().evaluate('SPY','1m',facts('1m',1,T+timedelta(minutes=1)),T,closed=True)
    def test_provisional_does_not_flip(self):
        e=BiasEngine();e.evaluate('SPY','1m',facts('1m',+1),T,closed=True)
        r=e.evaluate('SPY','1m',facts('1m',-1),T+timedelta(minutes=1),closed=False)
        self.assertEqual(r.confirmed_bias,'CALL')
    def test_opposite_requires_two_closes(self):
        e=BiasEngine();e.evaluate('SPY','1m',facts('1m',+1),T,closed=True)
        r=e.evaluate('SPY','1m',facts('1m',-1),T+timedelta(minutes=1),closed=True)
        self.assertEqual(r.confirmed_bias,'CALL')
        r=e.evaluate('SPY','1m',facts('1m',-1),T+timedelta(minutes=2),closed=True)
        self.assertEqual(r.confirmed_bias,'PUT')
    def test_reversal_independent(self):
        v=evaluate_reversal('CALL',dict(failed_breakout=True,relative_strength_breakdown=True,breadth_divergence=True,momentum_exhaustion=True))
        self.assertEqual(v.state,'REVERSAL_CONFIRMED')
    def test_pivot_not_known_on_origin(self):
        b=[Bar(T+timedelta(minutes=i),1,h,0.5,1,100) for i,h in enumerate([1,2,5,2,1])]
        p=confirmed_pivots(b,2,2)
        self.assertIn(('HIGH',2,b[4].end),p)
    def test_volume_slots(self):
        self.assertIsNone(volume_percentile(50,[1]*9))
        self.assertEqual(volume_percentile(15,[10]*10),1.0)

class OptionTests(TestCase):
    def test_moneyness_both_sides(self):
        self.assertEqual(moneyness(contract(strike=590),.005),'ITM')
        self.assertEqual(moneyness(contract(strike=610),.005),'OTM')
        self.assertEqual(moneyness(contract(strike=600),.005),'ATM')
        self.assertEqual(moneyness(contract(kind='PUT',strike=610),.005),'ITM')
    def test_positive_quote_candidate(self):
        x=select_contracts('CALL',[contract()],scenarios(),now=T)[0]
        self.assertEqual((x.status,x.moneyness),('CANDIDATE','ATM'))
        self.assertAlmostEqual(x.base_pnl,108.)
    def test_no_auto_zero_dte(self):
        x=select_contracts('CALL',[contract(days_to_expiry=0)],scenarios(),now=T)[0]
        self.assertIn('ZERO_DTE_DISABLED',x.reason_codes)
    def test_stale(self):
        x=select_contracts('CALL',[contract(quote_time=T-timedelta(minutes=1))],scenarios(),now=T)[0]
        self.assertIn('STALE_NBBO',x.reason_codes)
    def test_wide_spread(self):
        x=select_contracts('CALL',[contract(bid=2,ask=5)],scenarios(),now=T)[0]
        self.assertIn('WIDE_SPREAD',x.reason_codes)
    def test_missing_scenarios(self):
        x=select_contracts('CALL',[contract()],{},now=T)[0]
        self.assertIn('MISSING_SCENARIOS',x.reason_codes)
    def test_zero_dte_settlement_gate(self):
        x=select_contracts('CALL',[contract(days_to_expiry=0,settlement='UNKNOWN')],scenarios(),now=T,policy=ContractPolicy(enable_0dte=True))[0]
        self.assertIn('UNKNOWN_ZERO_DTE_SETTLEMENT',x.reason_codes)
    def test_nonpositive_base(self):
        s=scenarios();s['SPY_C_600']['base']=Scenario('base',4,45,0,0)
        x=select_contracts('CALL',[contract()],s,now=T)[0]
        self.assertIn('NONPOSITIVE_BASE_CASE',x.reason_codes)
