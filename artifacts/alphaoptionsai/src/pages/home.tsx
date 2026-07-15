import { TerminalDemo } from '@/components/terminal-demo';
import { FeatureGrid } from '@/components/feature-grid';
import { Methodology } from '@/components/methodology';
import { CommandTable } from '@/components/command-table';

export default function Home() {
  return (
    <div className="relative min-h-[100dvh] flex flex-col bg-background text-foreground overflow-hidden">
      <div className="noise-overlay" />
      
      {/* Grid Background */}
      <div className="absolute inset-0 z-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px]">
        <div className="absolute left-0 right-0 top-0 -z-10 m-auto h-[310px] w-[310px] rounded-full bg-primary opacity-[0.03] blur-[100px]"></div>
      </div>

      <nav className="relative z-10 w-full border-b border-border/50 bg-background/50 backdrop-blur-md">
        <div className="container mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-sm bg-primary" />
            <span className="font-mono text-sm font-bold tracking-tight">ALPHA_OPTIONS_AI</span>
          </div>
          <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider border border-border/50 px-3 py-1 rounded-full bg-secondary/50">
            Private Beta
          </div>
        </div>
      </nav>

      <main className="relative z-10 flex-1">
        {/* Hero Section */}
        <section className="container mx-auto px-6 pt-24 pb-24 lg:pt-32 lg:pb-32 flex flex-col lg:flex-row items-center gap-16">
          <div className="flex-1 flex flex-col items-start gap-8">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border bg-secondary/30 text-xs font-mono text-muted-foreground backdrop-blur-sm">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
              SYSTEM_ONLINE // ENGINE_V4
            </div>
            
            <h1 className="text-5xl lg:text-7xl font-bold tracking-tighter leading-[1.1] glow-text">
              One Decisive Answer.<br />
              <span className="text-muted-foreground">Zero Hype.</span>
            </h1>
            
            <p className="text-lg text-muted-foreground max-w-xl leading-relaxed">
              A disciplined options-trading analyst living inside your Discord server. We provide one verified answer per ticker: <strong className="text-success font-medium">CALL</strong>, <strong className="text-destructive font-medium">PUT</strong>, or <strong className="text-foreground font-medium">NO TRADE</strong>. And we'd rather say "no trade" than guess.
            </p>

            <div className="flex flex-wrap gap-4 pt-4">
              <div className="px-6 py-3 bg-primary text-primary-foreground font-medium text-sm rounded-md cursor-not-allowed opacity-90 flex items-center gap-2 relative overflow-hidden group">
                <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300 ease-out" />
                <span className="relative z-10">Server Invite Locked</span>
                <svg className="relative z-10" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              </div>
              <a href="#methodology" className="px-6 py-3 border border-border bg-secondary/20 text-foreground font-medium text-sm rounded-md hover:bg-secondary/40 transition-colors backdrop-blur-sm">
                View Methodology
              </a>
            </div>
          </div>
          
          <div className="flex-1 w-full max-w-2xl relative">
            <div className="absolute -inset-4 bg-primary/5 blur-2xl rounded-full" />
            <TerminalDemo />
          </div>
        </section>

        {/* Feature Grid */}
        <section id="methodology" className="border-t border-border/50 bg-secondary/10 pt-24 pb-24">
          <div className="container mx-auto px-6">
            <div className="mb-16">
              <h2 className="text-sm font-mono text-muted-foreground mb-4">THE_ALGORITHM</h2>
              <h3 className="text-3xl lg:text-4xl font-bold tracking-tight">Cold, calculated precision.</h3>
            </div>
            <FeatureGrid />
          </div>
        </section>

        {/* Deep Dive / Methodology */}
        <Methodology />

        {/* Command Reference */}
        <section className="border-t border-border/50 pt-24 pb-32 bg-secondary/5">
          <div className="container mx-auto px-6">
            <div className="mb-16 max-w-2xl">
              <h2 className="text-sm font-mono text-muted-foreground mb-4">COMMAND_CENTER</h2>
              <h3 className="text-3xl lg:text-4xl font-bold tracking-tight mb-4">You control the analysis.</h3>
              <p className="text-muted-foreground">Full terminal access directly within Discord. Execute commands to scan tickers, backtest strategies, and manage risk.</p>
            </div>
            <CommandTable />
          </div>
        </section>
      </main>

      <footer className="border-t border-border bg-background py-12">
        <div className="container mx-auto px-6 flex flex-col md:flex-row justify-between items-start gap-8">
          <div className="max-w-md">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-4 h-4 rounded-sm bg-primary/50" />
              <span className="font-mono text-sm font-bold text-muted-foreground tracking-tight">ALPHA_OPTIONS_AI</span>
            </div>
            <p className="text-xs text-muted-foreground/60 leading-relaxed text-justify">
              <strong>DISCLAIMER:</strong> AlphaOptionsAI is an educational tool, not financial advice. Options trading involves substantial risk of loss and is not suitable for all investors. The bot does not execute trades. Past performance of any trading system or methodology is not necessarily indicative of future results.
            </p>
          </div>
          <div className="text-xs font-mono text-muted-foreground text-right">
            <div>MODE: PRIVATE_BETA</div>
            <div>DATA: VERIFIED_ONLY</div>
            <div className="mt-4 opacity-50">&copy; {new Date().getFullYear()} AlphaOptionsAI.</div>
          </div>
        </div>
      </footer>
    </div>
  );
}
