import { useState, useEffect } from 'react';

export function TerminalDemo() {
  const [scenario, setScenario] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setScenario((s) => (s + 1) % 2);
    }, 8000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="w-full rounded-xl border border-border/50 bg-[#0a0a0c] shadow-2xl overflow-hidden font-mono text-sm flex flex-col h-[480px] relative z-10">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border/30 bg-[#0f0f12]">
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-border/50" />
          <div className="w-2.5 h-2.5 rounded-full bg-border/50" />
          <div className="w-2.5 h-2.5 rounded-full bg-border/50" />
        </div>
        <div className="mx-auto text-xs text-muted-foreground/50 tracking-wider uppercase">#trade-terminal</div>
      </div>
      
      <div className="p-4 md:p-6 flex flex-col gap-6 relative flex-1 overflow-hidden">
        {/* Scenario 0: CALL */}
        <div className={`transition-all duration-700 absolute w-full left-0 px-4 md:px-6 top-6 ${scenario === 0 ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-8 pointer-events-none'}`}>
          <div className="flex gap-3 mb-6">
            <div className="w-8 h-8 rounded-full bg-secondary flex-shrink-0 flex items-center justify-center text-xs text-muted-foreground font-sans">U</div>
            <div className="pt-1">
              <div className="text-primary font-medium font-sans text-xs mb-1">User</div>
              <div className="text-muted-foreground">/scan ticker: <span className="text-foreground">NVDA</span></div>
            </div>
          </div>
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-primary flex-shrink-0 flex items-center justify-center text-primary-foreground text-xs font-bold font-sans">α</div>
            <div className="flex-1 min-w-0">
              <div className="text-primary font-medium font-sans text-xs mb-2 flex items-center gap-2">
                AlphaOptionsAI <span className="px-1.5 py-0.5 rounded bg-[#5865F2] text-white text-[9px] font-sans font-bold leading-none tracking-wide">BOT</span>
              </div>
              <div className="border border-border/50 rounded-md overflow-hidden bg-[#111114] max-w-md w-full shadow-lg">
                <div className="border-l-2 border-success px-4 py-4 relative overflow-hidden">
                  <div className="absolute inset-0 bg-success/5 pointer-events-none" />
                  <div className="relative z-10">
                    <div className="text-lg font-bold font-sans text-foreground tracking-tight mb-1">DECISION: CALL</div>
                    <div className="text-success text-xs mb-4">Trade Score: 88/100 (A)</div>
                    <div className="space-y-4 text-xs">
                      <div>
                        <span className="text-muted-foreground text-[10px] tracking-wider">CONTRACT</span>
                        <div className="text-foreground mt-1 font-medium font-sans text-sm">NVDA 125C 11/15</div>
                        <div className="text-muted-foreground/70 mt-1 font-mono text-[10px]">Delta: 0.65 | Spread: $0.05 | Vol: 24k</div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 mt-1">
                        <div className="bg-background/50 px-2 py-1.5 rounded border border-border/30">
                          <span className="text-muted-foreground block text-[9px] uppercase tracking-wider mb-0.5">Trend</span>
                          <span className="text-success font-sans text-xs font-medium">Bullish</span>
                        </div>
                        <div className="bg-background/50 px-2 py-1.5 rounded border border-border/30">
                          <span className="text-muted-foreground block text-[9px] uppercase tracking-wider mb-0.5">Options Data</span>
                          <span className="text-success font-sans text-xs font-medium">Unusual Vol</span>
                        </div>
                      </div>
                      <div className="pt-2 border-t border-border/30 mt-3">
                        <span className="text-muted-foreground text-[10px] tracking-wider block mb-2">BACKTEST (LAST 6MO)</span>
                        <div className="flex gap-6">
                          <div>
                            <span className="text-[10px] text-muted-foreground block mb-0.5">Win Rate</span>
                            <span className="text-foreground font-medium font-sans text-sm">68.4%</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-muted-foreground block mb-0.5">Avg Return</span>
                            <span className="text-success font-medium font-sans text-sm">+42.1%</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Scenario 1: NO TRADE */}
        <div className={`transition-all duration-700 absolute w-full left-0 px-4 md:px-6 top-6 ${scenario === 1 ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8 pointer-events-none'}`}>
          <div className="flex gap-3 mb-6">
            <div className="w-8 h-8 rounded-full bg-secondary flex-shrink-0 flex items-center justify-center text-xs text-muted-foreground font-sans">U</div>
            <div className="pt-1">
              <div className="text-primary font-medium font-sans text-xs mb-1">User</div>
              <div className="text-muted-foreground">/scan ticker: <span className="text-foreground">TSLA</span></div>
            </div>
          </div>
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-primary flex-shrink-0 flex items-center justify-center text-primary-foreground text-xs font-bold font-sans">α</div>
            <div className="flex-1 min-w-0">
              <div className="text-primary font-medium font-sans text-xs mb-2 flex items-center gap-2">
                AlphaOptionsAI <span className="px-1.5 py-0.5 rounded bg-[#5865F2] text-white text-[9px] font-sans font-bold leading-none tracking-wide">BOT</span>
              </div>
              <div className="border border-border/50 rounded-md overflow-hidden bg-[#111114] max-w-md w-full shadow-lg">
                <div className="border-l-2 border-muted-foreground px-4 py-4 relative overflow-hidden">
                  <div className="absolute inset-0 bg-muted/5 pointer-events-none" />
                  <div className="relative z-10">
                    <div className="text-lg font-bold font-sans text-foreground tracking-tight mb-1">DECISION: NO TRADE</div>
                    <div className="text-muted-foreground text-xs mb-4">Trade Score: 42/100 (F)</div>
                    <div className="space-y-4 text-xs">
                      <div>
                        <span className="text-muted-foreground text-[10px] tracking-wider">REASON</span>
                        <div className="text-foreground/90 mt-1 leading-relaxed font-sans text-sm">Conflicting signals. Market context is bearish but momentum is bullish. IV is too elevated for a favorable risk/reward setup.</div>
                      </div>
                      <div className="p-2 border border-destructive/20 bg-destructive/5 text-destructive rounded text-[10px] uppercase tracking-wider text-center">
                        Capital Preservation Mode
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
