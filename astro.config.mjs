import { readFileSync } from 'node:fs';
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sidebar from './src/sidebar.generated.mjs';

// 站点地址与部署路径的唯一真源，sync_reports.py 也读它
const cfg = JSON.parse(readFileSync(new URL('./site.config.json', import.meta.url)));
const site = process.env.SITE ?? cfg.site;
const base = process.env.BASE ?? cfg.base;

export default defineConfig({
  site,
  base,
  integrations: [
    starlight({
      title: '里探投资报告',
      description: '公司、指数、商品与加密资产的价值投资研究。',
      defaultLocale: 'root',
      locales: {
        root: { label: '简体中文', lang: 'zh-CN' },
      },
      social: [],
      sidebar,
      lastUpdated: false,
      pagination: true,
      tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
      customCss: ['./src/styles/custom.css'],
      components: {},
    }),
  ],
});
