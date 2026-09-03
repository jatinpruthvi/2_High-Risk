import unittest
from datetime import datetime, timezone
from institutional_options.feed_quality import FeedHealthState, assess_fyers_payload
from institutional_options.derived_iv import implied_volatility

class FeedImprovementTests(unittest.TestCase):
    def payload(self):
        return {'data': {'optionsChain': [
            {'option_type':'','strike_price':-1,'ltp':100.0,'symbol':'NSE:X-INDEX'},
            {'option_type':'CE','strike_price':100,'ltp':5.1,'bid':5.0,'ask':5.2,'symbol':'NSE:X100CE'},
            {'option_type':'PE','strike_price':100,'ltp':4.9,'bid':4.8,'ask':5.0,'symbol':'NSE:X100PE'},
        ]}}
    def test_schema_incomplete_is_not_canonical(self):
        report=assess_fyers_payload(self.payload(), chain=object(), depth_status='APPLIED')
        self.assertEqual(report.state, FeedHealthState.SCHEMA_INCOMPLETE)
        self.assertFalse(report.canonical_eligible)
        self.assertTrue(report.derived_iv_research_eligible)
        self.assertIn('IV/Greeks absent', ' '.join(report.reasons))
    def test_market_closed_is_not_feed_failure(self):
        report=assess_fyers_payload({}, market_open=False)
        self.assertEqual(report.state, FeedHealthState.MARKET_CLOSED)
        self.assertFalse(report.derived_iv_research_eligible)
    def test_derived_iv_is_bounded_and_labelled(self):
        result=implied_volatility(5.0,100.0,100.0,'2026-12-31','CE',datetime(2026,8,31,tzinfo=timezone.utc))
        self.assertEqual(result.status,'DERIVED')
        self.assertEqual(result.source,'DERIVED_BLACK_SCHOLES_RESEARCH')
        self.assertGreater(result.value,0.0)

if __name__=='__main__': unittest.main()
