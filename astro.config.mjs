import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sidebar from './src/sidebar.generated.mjs';

export default defineConfig({
  site: 'https://insseek.github.io',
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
