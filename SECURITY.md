# Security policy

Never paste GitHub tokens, SSH keys, Binance keys, private data, ChatGPT sessions or billing screenshots into public issues. Use narrow GitHub tokens, revoke them if disclosed, and configure repository Actions permissions to `contents: read` except where explicitly required.

This project does not install itself as a background service, alter firewall rules, read credential stores or execute trading orders. The sample worker runs only static compute. Dispatch of a private repo may consume billable Actions time: always set a maximum spending limit on GitHub if available, keep the sample 5-minute worker timeout, and require explicit operator confirmation.

Please report vulnerabilities privately to a repository maintainer rather than posting exploit details publicly.


The optional public self-token path uses the runtime's ephemeral `GITHUB_TOKEN` only for the matching public repository and its default branch, with a checked allowlisted workflow. Do not pass tokens to public logs or artifacts. This path cannot route to other accounts or private repositories.
