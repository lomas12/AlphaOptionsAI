const commands = [
  { cmd: "/scan", args: "[ticker]", desc: "Full fundamental and technical scan returning Call, Put, or No Trade." },
  { cmd: "/options", args: "[ticker]", desc: "Raw options chain analysis, unusual volume, and IV skew." },
  { cmd: "/news", args: "[ticker]", desc: "Sentiment analysis of the last 24h of verified news sources." },
  { cmd: "/backtest", args: "[ticker] [strategy]", desc: "Run a historical backtest of a strategy on a specific ticker." },
  { cmd: "/history", args: "[ticker]", desc: "View the bot's past recommendations and actual outcomes." },
  { cmd: "/watchlist", args: "add/remove [ticker]", desc: "Manage tickers the bot monitors during market hours." },
  { cmd: "/alerts", args: "start/stop", desc: "Toggle automatic high-conviction alerts for your watchlist." },
  { cmd: "/setbalance", args: "[amount]", desc: "Set your paper or real portfolio balance for position sizing." },
  { cmd: "/setrisk", args: "[percentage]", desc: "Set max risk per trade (e.g., 2%)." },
  { cmd: "/performance", args: "", desc: "View the bot's global win rate and average return." },
  { cmd: "/top", args: "", desc: "View the highest scoring setups in the market right now." },
  { cmd: "/earnings", args: "[ticker]", desc: "Upcoming earnings data, historical moves, and implied volatility." },
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
