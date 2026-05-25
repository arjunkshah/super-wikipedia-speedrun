from wikispeedrun.solver import parse_page_html


HTML = """
<h1 id="firstHeading">Start</h1>
<div id="mw-content-text"><div class="mw-parser-output">
  <p>Demo page</p>
  <a href="/wiki/Target">Target</a>
  <a href="/wiki/File:Example">Ignored</a>
</div></div>
"""


page = parse_page_html("https://en.wikipedia.org/wiki/Start", HTML, lite=True)
assert page.title == "Start"
assert [link.title for link in page.links] == ["Target"]
