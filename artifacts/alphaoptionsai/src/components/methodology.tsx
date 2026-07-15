export function Methodology() {
  return (
    <section className="py-24 relative overflow-hidden">
      <div className="container mx-auto px-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
          <div>
            <h2 className="text-sm font-mono text-muted-foreground mb-4">RISK_MANAGEMENT</h2>
            <h3 className="text-3xl lg:text-4xl font-bold tracking-tight mb-6">Position sizing built in.</h3>
            <p className="text-lg text-muted-foreground leading-relaxed mb-10">
              Knowing what to trade is only half the battle. Knowing how much to risk keeps you in the game. AlphaOptionsAI maintains your virtual portfolio balance and risk tolerance right in Discord.
            </p>
            
            <div className="space-y-8">
              <div className="flex gap-5 items-start">
                <div className="w-8 h-8 rounded bg-secondary flex-shrink-0 flex items-center justify-center text-xs font-mono text-muted-foreground border border-border">1</div>
                <div>
                  <h4 className="font-bold text-base mb-2">Set Your Balance</h4>
                  <p className="text-xs text-muted-foreground font-mono bg-secondary/30 p-2.5 rounded border border-border/50 inline-block">/setbalance amount: 25000</p>
                </div>
              </div>
              <div className="flex gap-5 items-start">
                <div className="w-8 h-8 rounded bg-secondary flex-shrink-0 flex items-center justify-center text-xs font-mono text-muted-foreground border border-border">2</div>
                <div>
                  <h4 className="font-bold text-base mb-2">Define Max Risk</h4>
                  <p className="text-xs text-muted-foreground font-mono bg-secondary/30 p-2.5 rounded border border-border/50 inline-block">/setrisk percent: 2.0</p>
                </div>
              </div>
              <div className="flex gap-5 items-start">
                <div className="w-8 h-8 rounded bg-secondary flex-shrink-0 flex items-center justify-center text-xs font-mono text-muted-foreground border border-border">3</div>
                <div>
                  <h4 className="font-bold text-base mb-2">Get Sizing with Every Scan</h4>
                  <p className="text-sm text-muted-foreground/80 leading-relaxed max-w-md">Every recommended contract includes the exact number of contracts to buy to stay within your strict risk parameters.</p>
                </div>
              </div>
            </div>
          </div>
          
          <div className="relative">
            <div className="absolute -inset-0.5 bg-gradient-to-tr from-border to-transparent rounded-2xl blur opacity-30" />
            <div className="relative bg-[#0c0c0e] rounded-2xl border border-border/50 p-8 shadow-2xl">
              <div className="flex justify-between items-end border-b border-border/30 pb-5 mb-8">
                <div>
                  <div className="text-[10px] text-muted-foreground font-mono mb-1.5 uppercase tracking-widest">PORTFOLIO_RISK_MODEL</div>
                  <div className="text-3xl font-bold font-mono tracking-tight">$25,000.00</div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground font-mono mb-1.5 uppercase tracking-widest">MAX_RISK</div>
                  <div className="text-xl text-destructive font-mono font-bold">2.0% ($500)</div>
                </div>
              </div>
              
              <div className="space-y-4 font-mono text-xs">
                <div className="flex justify-between items-center p-4 rounded-lg bg-background/40 border border-border/30">
                  <span className="text-muted-foreground uppercase tracking-wider text-[10px]">Contract Cost</span>
                  <span className="font-medium">$1.45 ($145)</span>
                </div>
                <div className="flex justify-between items-center p-4 rounded-lg bg-primary/5 border border-primary/20 relative overflow-hidden">
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary" />
                  <span className="text-muted-foreground uppercase tracking-wider text-[10px] pl-2">Suggested Size</span>
                  <span className="text-primary font-bold">3 Contracts ($435)</span>
                </div>
                <div className="flex justify-between items-center p-4 rounded-lg bg-background/40 border border-border/30">
                  <span className="text-muted-foreground uppercase tracking-wider text-[10px]">Remaining Risk Cap</span>
                  <span className="text-success font-medium">$65</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
