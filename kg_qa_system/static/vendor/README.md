# Answer rendering dependencies

These browser assets are served locally; production rendering makes no CDN requests.
Exact versions, npm source URLs and verified package integrity hashes are recorded in
`manifest.json`. Each package directory contains its upstream license.

Run `python tools/vendor_renderer.py` from `kg_qa_system` to reproduce the assets.
Pass a package name to refresh only that pinned package. This command needs network
access; the application itself does not need network access to render Markdown.

The shared `answer-renderer.js` uses markdown-it and markdown-it-texmath to parse
Markdown and TeX, KaTeX for math, highlight.js for code, and DOMPurify to sanitize
the resulting fragment. Raw HTML is disabled, KaTeX trust is disabled, and scripts
remain restricted to the same origin. CSP allows inline style attributes because
KaTeX uses them to lay out fractions, scripts and other mathematical notation.

To run the browser regression page, start
`python -m http.server 8001 --bind 127.0.0.1` in `kg_qa_system` and open
`http://127.0.0.1:8001/tests/rendering.html`. It tests mixed content, code literals,
formula errors and unsafe content without contacting the model or changing chats.
This fixture is outside the production static mount.
