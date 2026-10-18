"""The read-only SQL guard must let analytics through and block everything else."""
import pytest

from gridiron.agent.warehouse import SqlNotAllowed, guard_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM main.mart_position_success",
        "select pos_group from main.mart_position_success order by champion_premium desc",
        "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
        "  -- comment\n select 1 ",
    ],
)
def test_allows_read_only_selects(sql):
    assert guard_sql(sql)  # returns cleaned SQL, truthy


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE main.dim_season",
        "UPDATE main.dim_season SET season = 1",
        "DELETE FROM raw.value_board",
        "INSERT INTO raw.value_board VALUES (1)",
        "ATTACH 'evil.db' AS e",
        "COPY raw.value_board TO 'out.csv'",
        "SELECT 1; SELECT 2",          # multiple statements
        "PRAGMA database_list",
        "CREATE TABLE t AS SELECT 1",
        "",                             # empty
    ],
)
def test_blocks_writes_and_escapes(sql):
    with pytest.raises(SqlNotAllowed):
        guard_sql(sql)
