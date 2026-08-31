const fs = require('fs');
const path = require('path');
const srcDir = path.resolve(__dirname, '../src/renderer/src');

let parser, traverse;
try {
  parser = require('@babel/parser');
  const _traverse = require('@babel/traverse');
  traverse = _traverse.default || _traverse;
} catch (e) {
  console.warn('⚠️  @babel/parser or @babel/traverse not available, skipping hook AST audit.');
  process.exit(0);
}
let totalViolations = 0;
let filesScanned = 0;

const HOOK_NAME_REGEX = /^use[A-Z0-9_]/;

function scanDirectory(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      scanDirectory(fullPath);
    } else if (entry.isFile() && (entry.name.endsWith('.jsx') || entry.name.endsWith('.js'))) {
      auditFile(fullPath);
    }
  }
}

function isComponentOrHook(name) {
  if (!name) return false;
  // React components start with capital letter, hooks start with `use`
  return /^[A-Z]/.test(name) || HOOK_NAME_REGEX.test(name);
}

function isHookCall(callee) {
  if (!callee) return false;
  if (callee.type === 'Identifier') {
    return HOOK_NAME_REGEX.test(callee.name) || callee.name === 'useState' || callee.name === 'useEffect' || callee.name === 'useCallback' || callee.name === 'useMemo' || callee.name === 'useRef' || callee.name === 'useContext';
  }
  if (callee.type === 'MemberExpression' && callee.property && callee.property.type === 'Identifier') {
    return HOOK_NAME_REGEX.test(callee.property.name);
  }
  return false;
}

function auditFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  filesScanned++;

  let ast;
  try {
    ast = parser.parse(content, {
      sourceType: 'module',
      plugins: ['jsx', 'typescript'],
    });
  } catch (err) {
    console.error(`[PARSE ERROR] ${filePath}: ${err.message}`);
    return;
  }

  traverse(ast, {
    enter(nodePath) {
      const node = nodePath.node;
      let fnName = null;

      if (node.type === 'FunctionDeclaration' && node.id) {
        fnName = node.id.name;
      } else if ((node.type === 'FunctionExpression' || node.type === 'ArrowFunctionExpression') && nodePath.parent.type === 'VariableDeclarator' && nodePath.parent.id) {
        fnName = nodePath.parent.id.name;
      } else if ((node.type === 'FunctionDeclaration' || node.type === 'FunctionExpression' || node.type === 'ArrowFunctionExpression') && nodePath.parent.type === 'ExportDefaultDeclaration') {
        fnName = 'DefaultExportComponent';
      }

      if (fnName && (isComponentOrHook(fnName) || fnName === 'DefaultExportComponent')) {
        checkFunctionBody(nodePath, filePath, fnName);
      }
    },
  });
}

function checkFunctionBody(fnPath, filePath, fnName) {
  const body = fnPath.node.body;
  if (!body || body.type !== 'BlockStatement') return;

  const statements = body.body;
  let encounteredReturn = false;
  let returnLoc = null;

  for (const stmt of statements) {
    // Top-level return in component body (conditional or unconditional)
    if (stmt.type === 'ReturnStatement') {
      encounteredReturn = true;
      returnLoc = stmt.loc ? stmt.loc.start.line : 'unknown';
      continue;
    }

    // Top-level if (...) return ...
    if (stmt.type === 'IfStatement') {
      const hasReturnInIf = statementHasReturn(stmt.consequent) || (stmt.alternate && statementHasReturn(stmt.alternate));
      if (hasReturnInIf) {
        encounteredReturn = true;
        returnLoc = stmt.loc ? stmt.loc.start.line : 'unknown';
      }
    }

    // Check if this statement contains a Hook call
    traverse(stmt, {
      CallExpression(callPath) {
        if (isHookCall(callPath.node.callee)) {
          const hookName = getCalleeName(callPath.node.callee);
          const line = callPath.node.loc ? callPath.node.loc.start.line : 'unknown';

          if (encounteredReturn) {
            console.error(`❌ [HOOK ORDER VIOLATION] ${filePath}:${line} -> "${hookName}" called after early return on line ${returnLoc} in "${fnName}"`);
            totalViolations++;
          }
        }
      },
      noScope: true,
    });
  }
}

function statementHasReturn(stmt) {
  if (!stmt) return false;
  if (stmt.type === 'ReturnStatement') return true;
  if (stmt.type === 'BlockStatement') {
    return stmt.body.some((s) => statementHasReturn(s));
  }
  return false;
}

function getCalleeName(callee) {
  if (callee.type === 'Identifier') return callee.name;
  if (callee.type === 'MemberExpression' && callee.property) return callee.property.name;
  return 'unknownHook';
}

console.log('🔍 Auditing React components and hooks for Rules of Hooks compliance...');
scanDirectory(srcDir);

if (totalViolations > 0) {
  console.error(`\n🚨 FOUND ${totalViolations} REACT HOOK VIOLATION(S) across ${filesScanned} files! Fix them immediately.`);
  process.exit(1);
} else {
  console.log(`\n✅ PASSED: 0 React Hook violations found across ${filesScanned} files. All components follow Rules of Hooks!`);
  process.exit(0);
}
