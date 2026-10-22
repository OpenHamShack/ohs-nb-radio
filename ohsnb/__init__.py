"""QO-100 NB: a QO-100 narrowband transceiver daemon.

This package is being built by several agents in parallel, each owning a
slice of the tree (see DESIGN.md). This file deliberately does nothing but
mark the package -- the daemon entry point, device layer and DSP chain are
someone else's files landing alongside ohsnb/modes/, and importing this
package must not have side effects (opening devices, starting threads) that
would make one agent's work depend on another's being finished yet.
"""
