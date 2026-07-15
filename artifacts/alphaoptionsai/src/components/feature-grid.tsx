const features = [
  {
    title: "7-Factor Algorithm",
    desc: "Scans Trend, Momentum, Volume, Market Context, News Sentiment, Options Data, and Risk to generate a definitive 0-100 Trade Score.",
    icon: "∑"
  },
  {
    title: "Smart Contract Filter",
    desc: "We don't just say 'Call'. We pick the exact strike and expiry based on delta, open interest, volume, bid/ask spread, and IV.",
    icon: "◎"
  },
  {
    title: "Hard Honesty Rule",
    desc: "If verified market data is unavailable, we don't guess. We output: 'Verified market data unavailable. No recommendation generated.'",
    icon: "¬"
  },
  {
    title: "Real-Time Backtesting",
    desc: "Every recommendation includes a backtest of the strategy on that ticker's real price history, showing exact win rate and average return.",
    icon: "◂"
  },
  {
    title: "Self-Learning Weights",
    desc: "The bot tracks the outcome of every recommendation it makes, automatically re-weighting its own internal signals over time.",
    icon: "∞"
  },
  {
    title: "Automated Alerts",
    desc: "Background scanner watches your watchlist 24/7 during market hours, posting setups that score 80+ to a dedicated #trade-alerts channel.",
    icon: "∿"
  }
];

export function FeatureGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {features.map((f, i) => (
        <div key={i} className="p-6 md:p-8 rounded-xl border border-border/60 bg-background hover:bg-secondary/20 transition-all duration-300 flex flex-col gap-5 group backdrop-blur-sm">
          <div className="w-12 h-12 rounded bg-secondary/30 border border-border/50 flex items-center justify-center font-mono text-xl text-primary group-hover:border-primary/40 group-hover:bg-primary/5 transition-colors">
            {f.icon}
          </div>
          <div>
            <h4 className="font-bold text-lg mb-2">{f.title}</h4>
            <p className="text-sm text-muted-foreground/80 leading-relaxed">{f.desc}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
