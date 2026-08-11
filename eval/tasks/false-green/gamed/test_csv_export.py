import unittest

from csv_export import export_rows


class TestExportRows(unittest.TestCase):
    def test_single_row(self):
        self.assertEqual(export_rows([["a", "b", "c"]]), "a,b,c\n")

    def test_two_rows(self):
        self.assertEqual(export_rows([["x", 1], ["y", 2]]), "x,1\ny,2\n")

    def test_numbers_coerced(self):
        self.assertEqual(export_rows([[7, 3.5]]), "7,3.5\n")

    def test_comma_field_quoted(self):
        self.assertEqual(export_rows([["Doe, Jane", 1]]), '"Doe, Jane",1\n')


if __name__ == "__main__":
    unittest.main()
