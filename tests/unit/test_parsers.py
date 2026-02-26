"""Tests for PDF and HTML parsers."""


from exnot.parser.html_parser import HtmlParser


class TestHtmlParser:
    def setup_method(self):
        self.parser = HtmlParser()

    def test_extract_simple_table(self):
        html = b"""
        <html><body>
        <h2>Transaction Fees</h2>
        <table>
            <tr><th>Participant</th><th>Maker</th><th>Taker</th></tr>
            <tr><td>Customer</td><td>-$0.25</td><td>$0.50</td></tr>
            <tr><td>Market Maker</td><td>-$0.20</td><td>$0.45</td></tr>
        </table>
        </body></html>
        """
        doc = self.parser.extract(html)

        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert table.headers == ["Participant", "Maker", "Taker"]
        assert len(table.rows) == 2
        assert table.rows[0] == ["Customer", "-$0.25", "$0.50"]

    def test_extract_multiple_tables(self):
        html = b"""
        <html><body>
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        <table>
            <tr><th>C</th><th>D</th></tr>
            <tr><td>3</td><td>4</td></tr>
        </table>
        </body></html>
        """
        doc = self.parser.extract(html)
        assert len(doc.tables) == 2

    def test_skip_single_row_tables(self):
        """Tables with only headers and no data rows should be skipped."""
        html = b"""
        <html><body>
        <table>
            <tr><th>Only Header</th></tr>
        </table>
        </body></html>
        """
        doc = self.parser.extract(html)
        assert len(doc.tables) == 0

    def test_full_text_extraction(self):
        html = b"""
        <html><body>
        <h1>Fee Schedule</h1>
        <p>Effective January 1, 2026</p>
        <script>var x = 1;</script>
        </body></html>
        """
        doc = self.parser.extract(html)
        assert "Fee Schedule" in doc.full_text
        assert "Effective January 1, 2026" in doc.full_text
        assert "var x" not in doc.full_text  # script removed

    def test_table_title_from_heading(self):
        html = b"""
        <html><body>
        <h3>Penny Pilot Fees</h3>
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        </body></html>
        """
        doc = self.parser.extract(html)
        assert doc.tables[0].title == "Penny Pilot Fees"
