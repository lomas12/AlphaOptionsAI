const commands = [
  { cmd: "/scan", args: "[ticker]", desc: "Full technical and options scan returning one decision: Call, Put, or No Trade." },
  { cmd: "/options", args: "[ticker]", desc: "Options chain analysis: greeks, IV rank, max pain, and put/call ratio." },
  { cmd: "/news", args: "[ticker]", desc: "Latest verified headlines, analyst actions, insider activity, and SEC filings." },
  { cmd: "/backtest", args: "[ticker] [period]", desc: "Backtest the EMA crossover strategy on real historical prices." },
  { cmd: "/history", args: "[ticker]", desc: "View the bot's past recommendations and actual outcomes." },
  { cmd: "/universe", args: "", desc: "Universal scanner status: optionable-stock universe size and top live candidates." },
  { cmd: "/alerts", args: "", desc: "Show the most recent automatic high-conviction alerts." },
  { cmd: "/setbalance", args: "[amount]", desc: "Set your account balance for position sizing." },
  { cmd: "/setrisk", args: "[percentage]", desc: "Set max risk per trade (e.g., 2%)." },
  { cmd: "/performance", args: "", desc: "Accuracy breakdown of past recommendations by ticker." },
  { cmd: "/top", args: "", desc: "Leaderboard of the best-performing strategy setups so far." },
  { cmd: "/earnings", args: "[ticker]", desc: "Upcoming earnings date, days remaining, and EPS / revenue estimates." },
];

export function CommandTable() {
  return (
    <div className="rounded-xl border border-border/60 bg-background/50 overflow-hidden backdrop-blur-sm shadow-xl">
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono bg-secondary/30 border-b border-border/50">
            <tr>
              <th className="px-6 py-4 font-normal">COMMAND</th>
              <th className="px-6 py-4 font-normal">ARGUMENTS</th>
              <th className="px-6 py-4 font-normal">DESCRIPTION</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {commands.map((c, i) => (
              <tr key={i} className="hover:bg-secondary/20 transition-colors group">
                <td className="px-6 py-4 font-mono font-medium text-primary whitespace-nowrap">{c.cmd}</td>
                <td className="px-6 py-4 font-mono text-muted-foreground whitespace-nowrap text-xs">{c.args}</td>
                <td className="px-6 py-4 text-muted-foreground/80 group-hover:text-foreground transition-colors">{c.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
