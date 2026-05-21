<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks logo" width="800">
</p>

# Husks

**Build Husks, not vibes.**

Husks is a tiny build calculus for nondeterministic work. Model calls are not 
agents; they are bounded `oracle` recipes inside declared rules. Each rule names 
its inputs, outputs, tools, and fuel. The runtime walks the graph, checks the 
residue, seals artifacts, and records the trace.
