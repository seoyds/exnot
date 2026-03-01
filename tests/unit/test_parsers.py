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

    def test_extract_with_rendered_text(self):
        """When rendered_text is provided, use it as full_text instead of get_text()."""
        html = b"""
        <html><body>
        <nav>Navigation Menu Item 1 Item 2 Item 3</nav>
        <h2>Transaction Fees</h2>
        <table>
            <tr><th>Participant</th><th>Fee</th></tr>
            <tr><td>Customer</td><td>$0.50</td></tr>
        </table>
        <footer>Copyright 2026 All Rights Reserved</footer>
        </body></html>
        """
        rendered = "Transaction Fees\nParticipant\tFee\nCustomer\t$0.50"
        doc = self.parser.extract(html, rendered_text=rendered)

        # full_text should be the rendered text, not BeautifulSoup's get_text()
        assert doc.full_text == rendered
        assert "Navigation Menu" not in doc.full_text
        # Tables should still be parsed from raw HTML
        assert len(doc.tables) == 1
        assert doc.tables[0].headers == ["Participant", "Fee"]

    def test_skip_layout_tables_too_many_columns(self):
        """Tables with more than 20 columns are layout tables and should be skipped."""
        # Build a table with 25 columns
        headers = "".join(f"<th>Col{i}</th>" for i in range(25))
        row = "".join(f"<td>{i}</td>" for i in range(25))
        html = f"""
        <html><body>
        <table>
            <tr>{headers}</tr>
            <tr>{row}</tr>
        </table>
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        </body></html>
        """.encode()
        doc = self.parser.extract(html)
        # Only the normal 2-column table should be extracted
        assert len(doc.tables) == 1
        assert doc.tables[0].headers == ["A", "B"]

    def test_skip_layout_tables_huge_cells(self):
        """Tables with cells containing more than 5000 chars are layout tables."""
        huge_text = "X" * 6000
        html = f"""
        <html><body>
        <table>
            <tr><th>Nav</th><th>Content</th></tr>
            <tr><td>Menu</td><td>{huge_text}</td></tr>
        </table>
        <table>
            <tr><th>Fee</th><th>Amount</th></tr>
            <tr><td>Maker</td><td>$0.25</td></tr>
        </table>
        </body></html>
        """.encode()
        doc = self.parser.extract(html)
        assert len(doc.tables) == 1
        assert doc.tables[0].headers == ["Fee", "Amount"]

    def test_extract_without_rendered_text_unchanged(self):
        """Without rendered_text, behavior is unchanged (uses get_text())."""
        html = b"""
        <html><body>
        <h1>Fee Schedule</h1>
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        </body></html>
        """
        doc = self.parser.extract(html)
        assert "Fee Schedule" in doc.full_text
        assert len(doc.tables) == 1
