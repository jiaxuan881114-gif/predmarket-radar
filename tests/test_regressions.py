"""Network-free regressions for API boundaries, failure paths and packaging."""
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from predmarket.agent.analyst import MarketAnalyst, _build_brief
from predmarket.cli import _load_fixtures, cmd_run
from predmarket.clients.base import BaseHttpClient
from predmarket.clients.kalshi import KalshiClient
from predmarket.models import MarketSnapshot, AnomalySignal, Venue
from predmarket.pipeline import Collector, SnapshotStore
from predmarket.analysis import find_cross_venue_dislocations


def market(**kw):
    return MarketSnapshot(**dict(venue='polymarket', market_id='x', question='Will Fed cut 25 points in 2026?', yes_prob=.6, **kw))


class Regressions(unittest.TestCase):
    def test_current_kalshi_schema(self):
        snap = KalshiClient()._normalize(dict(ticker='K', title='Question', status='active',
            yes_bid_dollars='0.56', yes_ask_dollars='0.60', last_price_dollars='0.10',
            volume_fp='123.50', volume_24h_fp='20.25', open_interest_fp='30.00',
            close_time='2026-12-01T00:00:00Z'))
        self.assertAlmostEqual(snap.yes_prob, .58)
        self.assertEqual(snap.volume, 123.5)
        self.assertEqual(snap.volume_unit, 'contracts')
        self.assertEqual(snap.end_date.year, 2026)
        self.assertTrue(snap.active)

    def test_legacy_and_invalid_prices(self):
        c = KalshiClient()
        base = dict(ticker='K', title='Question', status='open')
        self.assertAlmostEqual(c._normalize(dict(base, yes_bid=40, yes_ask=60)).yes_prob, .5)
        self.assertIsNone(c._normalize(dict(base, last_price='invalid')))
        self.assertIsNone(c._normalize(dict(base, last_price_dollars='NaN')))
        self.assertIsNone(c._normalize(dict(base, last_price=50, market_type='scalar')))

    def test_snapshot_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(tmp)
            paths = [store.write([market()]) for _ in range(20)]
            self.assertEqual(len(set(paths)), 20)
            self.assertEqual(len(store.previous_two()[0]), 1)

    def test_legacy_snapshot_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(tmp)
            for stamp, p in [('20260101T000000Z', .4), ('20260101T000000.500000Z', .6)]:
                m = market().model_copy(update={'yes_prob': p})
                (Path(tmp)/f'snapshot_{stamp}.json').write_text(json.dumps({'markets':[m.model_dump(mode='json')]}))
            self.assertEqual(store.latest()[0].yes_prob, .6)

    def test_collector_uses_latest_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(tmp)
            store.write([market().model_copy(update={'yes_prob':.4})])
            c = Collector(store)
            c.poly.list_active_markets = Mock(return_value=[market()])
            c.kalshi.list_active_markets = Mock(side_effect=RuntimeError('unavailable'))
            report = c.collect()
            self.assertAlmostEqual(report.probability_moves[0]['delta'], .2)
            self.assertEqual(len(report.errors), 1)

    def test_total_failure_never_analyses_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(tmp)
            store.write([market()])
            c = Collector(store)
            c.poly.list_active_markets = Mock(side_effect=RuntimeError('offline'))
            c.kalshi.list_active_markets = Mock(side_effect=RuntimeError('offline'))
            args = argparse.Namespace(data_dir=tmp, limit=5, top_n=5, agent_limit=5, out=None)
            analyst = Mock()
            analyst.judge.return_value = []
            with patch('predmarket.cli.Collector', return_value=c), patch('predmarket.cli.build_analyst', return_value=analyst):
                self.assertEqual(cmd_run(args), 1)
            self.assertEqual(analyst.judge.call_args.args[0], [])
            report = json.loads((Path(tmp)/'report_latest.json').read_text())
            self.assertEqual(report['totals']['markets_fetched'], 0)
            self.assertEqual(len(report['errors']), 2)

    def test_signal_identity_includes_venue(self):
        anomaly = AnomalySignal(type='wide_spread', severity='warning', market_id='x', venue='kalshi', detail='test')
        self.assertEqual(_build_brief(market(), [], [anomaly])['anomalies'], [])

    def test_llm_cannot_change_market_identity(self):
        response = Mock()
        response.json.return_value = {'choices':[{'message':{'content':json.dumps(dict(
            market_id='wrong', venue='polymarket', question='wrong', thesis='test', direction='NEUTRAL', conviction=1,
            suggested_action='monitor', confidence_in_market=.5))}}]}
        with patch('predmarket.agent.analyst.requests.post', return_value=response):
            with self.assertRaises(ValueError):
                MarketAnalyst(api_key='test-placeholder').judge_one(_build_brief(market(), [], []))

    def test_retry_server_error_then_success(self):
        session = Mock()
        session.get.side_effect = [Mock(status_code=503, headers={}), Mock(status_code=200, json=Mock(return_value={'ok':True}))]
        with patch('predmarket.clients.base.time.sleep') as sleep:
            self.assertEqual(BaseHttpClient(session=session)._get('/test'), {'ok':True})
            sleep.assert_called_once()

    def test_retry_after_http_date_does_not_crash(self):
        session = Mock()
        session.get.return_value = Mock(status_code=429, headers={'Retry-After':'Wed, 21 Oct 2026 07:28:00 GMT'})
        with patch('predmarket.clients.base.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 429'):
                BaseHttpClient(session=session, max_retries=2)._get('/test')
            sleep.assert_called_once()

    def test_cross_venue_rejects_different_strikes_and_closed(self):
        p = market()
        k = p.model_copy(update={'venue':Venue.KALSHI, 'yes_prob':.3,
            'question':'Will Fed cut 50 points in 2026?'})
        self.assertEqual(find_cross_venue_dislocations([p,k]), [])
        k = k.model_copy(update={'question':p.question, 'closed':True})
        self.assertEqual(find_cross_venue_dislocations([p,k]), [])

    def test_demo_has_packaged_fixtures(self):
        self.assertEqual(len(_load_fixtures()), 10)


if __name__ == '__main__':
    unittest.main()
