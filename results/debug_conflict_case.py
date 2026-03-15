from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis  # noqa: E402
from analysis import ChannelCandidate  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump detailed interference metrics for one candidate/permit pair.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--permit", required=True)
    parser.add_argument("--channel-ab", required=True)
    parser.add_argument("--channel-ba", required=True)
    parser.add_argument("--freq-ab", type=float, required=True)
    parser.add_argument("--freq-ba", type=float, required=True)
    parser.add_argument("--pol", required=True)
    args = parser.parse_args()

    request = parse_wlr_file(Path(args.wlr))
    result = analysis.analyze_wlr_request(request)
    link = next(link for link in result.candidate_links if link.permit_number == args.permit)
    candidate = ChannelCandidate(
        plan_symbol=request.plan_symbol,
        channel_ab=args.channel_ab,
        channel_ba=args.channel_ba,
        freq_ab_ghz=args.freq_ab,
        freq_ba_ghz=args.freq_ba,
        polarization=args.pol,
    )
    metrics = analysis.estimate_interference_metrics(request, candidate, link)
    payload = {
        "permit": args.permit,
        "candidate": {
            "channel_ab": candidate.channel_ab,
            "channel_ba": candidate.channel_ba,
            "freq_ab_ghz": candidate.freq_ab_ghz,
            "freq_ba_ghz": candidate.freq_ba_ghz,
            "polarization": candidate.polarization,
        },
        "link": {
            "link_id": link.link_id,
            "atpc_ab_db": link.emission_ab.atpc_attenuation_db,
            "atpc_ba_db": link.emission_ba.atpc_attenuation_db,
            "eirp_ab_dbm": link.emission_ab.eirp_dbm,
            "eirp_ba_dbm": link.emission_ba.eirp_dbm,
            "plan_ab": link.emission_ab.plan_symbol,
            "plan_ba": link.emission_ba.plan_symbol,
            "pol_ab": link.emission_ab.polarization,
            "pol_ba": link.emission_ba.polarization,
        },
        "metrics": metrics,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
