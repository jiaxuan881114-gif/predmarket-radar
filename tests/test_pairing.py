"""Regressions for collection coverage and conservative event equivalence."""
import json
import unittest
import requests
from unittest.mock import Mock, patch

from pydantic import ValidationError
from predmarket.agent.pairing import PairMatcher, PairDecision, candidate_pairs
from predmarket.clients.kalshi import KalshiClient
from predmarket.clients.polymarket import PolymarketClient
from predmarket.models import MarketSnapshot, Venue


def pair():
    p = MarketSnapshot(venue='polymarket', market_id='P',
        question='Will the Fed cut rates in December 2026?', yes_prob=.5,
        raw={'description':'Fed target cut at December 2026 meeting, official Fed announcement.'})
    k = p.model_copy(update={'venue': Venue.KALSHI,
        'market_id':'K', 'yes_prob':.5, 'raw':{'rules_primary':p.raw['description']}})
    return p, k


def decision(**overrides):
    return dict(polymarket_id='P', kalshi_id='K', status='same_event', confidence=.95,
        subject='match', condition='match', time_window='match', resolution_rules='match',
        yes_polarity='match', reason='Rules agree', missing_information=[], **overrides)


class PairingTests(unittest.TestCase):
    def review(self, payload, p=None, k=None):
        p0, k0 = pair()
        response = Mock()
        response.json.return_value = {'choices':[{'message':{'content':json.dumps(payload)}}]}
        with patch('predmarket.agent.pairing.requests.post', return_value=response):
            return PairMatcher(api_key='test-placeholder').review(p or p0, k or k0)

    def test_recall_does_not_require_price_gap(self):
        self.assertEqual(len(candidate_pairs(list(pair()))), 1)

    def test_dates_closed_and_duplicate_inputs(self):
        p, k = pair()
        self.assertEqual(len(candidate_pairs([p,p,k,k])), 1)
        self.assertEqual(candidate_pairs([p,k.model_copy(update={'closed':True})]), [])
        self.assertEqual(candidate_pairs([p,k.model_copy(update={'question':'Will the Fed cut rates in December 2027?'})]), [])

    def test_paraphrased_strikes_rank_above_annual_questions(self):
        p,k=pair()
        p=p.model_copy(update={'question':'Will the Fed increase interest rates by 25 bps after the December 2026 meeting?'})
        k=k.model_copy(update={'question':'Will the Federal Reserve Hike rates by 25bps at their December 2026 meeting?'})
        annual=p.model_copy(update={'market_id':'annual','question':'Another Fed rate hike in 2026?'})
        candidates=candidate_pairs([p,annual,k])
        self.assertEqual(candidates[0][0].market_id,'P')

    def test_identity_must_match(self):
        d=decision();d['kalshi_id']='wrong'
        with self.assertRaises(ValueError): self.review(d)

    def test_missing_rules_never_confirmed(self):
        p,k=pair();p=p.model_copy(update={'raw':{}})
        self.assertEqual(self.review(decision(),p=p,k=k).status,'uncertain')

    def test_inconsistent_dimensions_low_confidence_and_missing_info(self):
        for field,value in [('yes_polarity','different'),('condition','unknown'),
                            ('confidence',.8),('missing_information',['source'])]:
            d=decision();d[field]=value
            self.assertEqual(self.review(d).status,'uncertain')

    def test_same_event_retained_when_evidence_complete(self):
        self.assertEqual(self.review(decision()).status,'same_event')

    def test_transient_tls_failure_retried_once(self):
        p,k=pair()
        response=Mock()
        response.json.return_value={'choices':[{'message':{'content':json.dumps(decision())}}]}
        with patch('predmarket.agent.pairing.requests.post',
                   side_effect=[requests.exceptions.SSLError('transport'),response]) as post:
            result=PairMatcher(api_key='test-placeholder').review(p,k)
        self.assertEqual(result.status,'same_event')
        self.assertEqual(post.call_count,2)

    def test_http_auth_failure_not_retried(self):
        p,k=pair()
        response=Mock(status_code=401)
        response.raise_for_status.side_effect=requests.HTTPError(response=response)
        with patch('predmarket.agent.pairing.requests.post',return_value=response) as post:
            r=PairMatcher(api_key='test-placeholder').match([p,k])
        self.assertEqual(post.call_count,1)
        self.assertEqual(r['errors'][0]['http_status'],401)

    def test_invalid_status_rejected(self):
        d=decision();d['status']='probably'
        with self.assertRaises(ValidationError): PairDecision.model_validate(d)

    def test_no_gap_for_uncertain_and_errors_visible(self):
        matcher=PairMatcher(api_key='test-placeholder')
        d=decision();d['status']='uncertain'
        with patch.object(matcher,'review',return_value=PairDecision.model_validate(d)):
            r=matcher.match(list(pair()))
        self.assertEqual(r['confirmed_pairs'],[])
        self.assertIsNone(r['decisions'][0]['dislocation_pp'])
        with patch.object(matcher,'review',side_effect=ValueError('untrusted server error')):
            r=matcher.match(list(pair()))
        self.assertEqual(len(r['errors']),1)
        self.assertNotIn('untrusted',json.dumps(r))

    def test_kalshi_excludes_combos_and_keeps_rules(self):
        c=KalshiClient();c._get=Mock(return_value={'markets':[]})
        c.list_active_markets(series_ticker='KXFEDDECISION')
        self.assertEqual(c._get.call_args.kwargs['params']['mve_filter'],'exclude')
        self.assertEqual(c._get.call_args.kwargs['params']['series_ticker'],'KXFEDDECISION')
        m=c._normalize(dict(ticker='K',title='Fed',last_price=50,rules_primary='official rules',yes_sub_title='25bps'))
        self.assertEqual(m.raw['rules_primary'],'official rules')
        self.assertEqual(m.raw['yes_sub_title'],'25bps')

    def test_polymarket_pagination_and_description(self):
        c=PolymarketClient()
        def page(path,params):
            return [{'id':str(i),'question':'Fed','outcomes':['Yes','No'],
                     'outcomePrices':['0.5','0.5'],'description':'official rule'}
                    for i in range(params['offset'],params['offset']+params['limit'])]
        c._get=Mock(side_effect=page)
        ms=c.list_active_markets(limit=205)
        self.assertEqual(len(ms),205)
        self.assertEqual([call.kwargs['params']['offset'] for call in c._get.call_args_list],[0,100,200])
        self.assertEqual(ms[0].raw['description'],'official rule')


if __name__=='__main__': unittest.main()
