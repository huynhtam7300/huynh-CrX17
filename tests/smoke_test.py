from core.collector.market_collector import run as collect_run
from core.decision.decision_maker import run_decision

def main():
    collect_run()
    sig = run_decision()
    assert "decision" in sig
    print("[smoke] OK:", sig)

if __name__ == "__main__":
    main()