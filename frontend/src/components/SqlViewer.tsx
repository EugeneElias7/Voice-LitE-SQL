const KEYWORDS = new Set([
  'SELECT', 'FROM', 'WHERE', 'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET',
  'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON', 'AS', 'AND', 'OR', 'NOT',
  'IN', 'IS', 'NULL', 'LIKE', 'BETWEEN', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
  'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'ASC', 'DESC', 'WITH', 'UNION',
  'ALL', 'EXISTS', 'SUBSTR', 'CAST', 'COALESCE', 'IFNULL', 'ROUND', 'DATE',
])

function highlightToken(token: string, className: string, key: number): JSX.Element {
  return (
    <span key={key} className={className}>
      {token}
    </span>
  )
}

export function highlightSql(sql: string): JSX.Element[] {
  const nodes: JSX.Element[] = []
  const pattern =
    /(--[^\n]*|'[^']*'|"(?:[^"]|"")*"|\b\d+(?:\.\d+)?\b|[A-Za-z_][A-Za-z0-9_]*)/g
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = pattern.exec(sql)) !== null) {
    if (match.index > last) {
      nodes.push(highlightToken(sql.slice(last, match.index), 'sql-plain', key))
      key += 1
    }
    const text = match[0]
    let className = 'sql-plain'
    if (text.startsWith('--')) className = 'sql-comment'
    else if (text.startsWith("'") || text.startsWith('"')) className = 'sql-string'
    else if (/^\d/.test(text)) className = 'sql-number'
    else if (KEYWORDS.has(text.toUpperCase())) className = 'sql-keyword'
    else className = 'sql-ident'
    nodes.push(highlightToken(text, className, key))
    last = match.index + text.length
    key += 1
  }
  if (last < sql.length) nodes.push(highlightToken(sql.slice(last), 'sql-plain', key))
  return nodes
}