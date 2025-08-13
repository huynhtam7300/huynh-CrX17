# CrX 1.7 – Sơ đồ Pipeline (CORE → Phase A)

```mermaid
flowchart LR
  subgraph S[Auto Runner]
    A0[auto_runner.py]
  end

  subgraph Cfg[Configs]
    CF[feature_flags.yaml]
    RL[risk_limits.yaml]
    KP[kpi_policy.yaml]
    CJ[config.json]
  end

  subgraph COL[Collector]
    C1[core/collector/market_collector.py]
  end

  subgraph ETL[Feature ETL]
    F1[core/feature_etl/cleaner.py]
    F2[core/feature_etl/alignment.py]
    F3[core/feature_etl/selector.py]
  end

  subgraph ANA[Analyzer · Left]
    T1[core/analyzer/technical_analyzer.py]
    LA[core/aggregators/left_agg.py]
  end

  subgraph CAP[Capital]
    B1[core/capital/bandit_optimizer.py]
    FND[core/capital/funding_optimizer.py]
  end

  subgraph DEC[Decision]
    D1[core/decision/decision_maker.py]
    MC[core/decision/meta_controller.py]
  end

  subgraph EXE[Execution]
    E1[core/execution/order_executor.py]
    E2[core/execution/order_monitor.py]
  end

  subgraph KPI[KPI]
    KT[core/kpi/kpi_tracker.py]
  end

  subgraph MEM[Memory/Logs]
    DH[(data/decision_history.json)]
    TH[(data/trade_history.json)]
  end

  subgraph NOTI[Notifier/Report]
    NT[notifier/notify_telegram.py]
    RD[report/report_daily.py]
  end

%% Orchestration
A0 --> C1
A0 --> RD
A0 --> KT

%% Data flow
C1 --> F1 --> F2 --> F3 --> T1 --> LA --> D1
D1 --> MC --> CAP
CAP -->|size, funding, kpi| D1
D1 -->|decision.json| E1 --> E2 --> TH
D1 --> DH

%% KPI & Noti
KT --> D1
E1 --> NT
E2 --> NT
RD --> NT

%% Configs influence
CF -. flags .-> A0
RL -. limits .-> D1
KP -. policies .-> KT
CJ -. runtime .-> A0