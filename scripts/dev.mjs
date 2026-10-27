// 开发服务器：改了生成的侧边栏或站点配置，自动重启 astro dev。
//
// 为什么需要这层包装：sidebar 是 astro.config.mjs 在启动时 import 的模块，
// Astro 的原地重启不会重新读它——改动之后页面仍显示旧侧栏，只有新进程才会。
import { spawn } from 'node:child_process';
import { watch } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const watchFiles = ['src/sidebar.generated.mjs', 'site.config.json'];
// 直接跑 astro 的 node 入口，不用 npx：npx 会多一层进程，杀不干净会占着端口，
// 新进程于是绑不上 4321，旧的继续用旧配置服务——看起来就像"没重启"。
const ASTRO_BIN = join(root, 'node_modules', 'astro', 'bin', 'astro.mjs');

let child;
let stopping = false;
let restarting = false;
let timer;

function start() {
  child = spawn(process.execPath, [ASTRO_BIN, 'dev', ...process.argv.slice(2)], {
    cwd: root,
    stdio: 'inherit',
  });
  child.on('exit', (code) => {
    if (stopping) process.exit(0);
    if (restarting) {
      restarting = false;
      start();
      return;
    }
    process.exit(code ?? 0);
  });
}

function restart() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    if (stopping || restarting || !child) return;
    console.log('\n[dev] 生成文件变了，重启 astro dev…');
    restarting = true;
    child.kill('SIGTERM');
  }, 400);
}

start();
for (const file of watchFiles) {
  watch(join(root, file), restart);
}

process.on('SIGINT', () => {
  stopping = true;
  child?.kill('SIGINT');
  process.exit(0);
});
