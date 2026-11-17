import adapter from '@sveltejs/adapter-auto';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	// (15/11, crouton-alpha) O Tailscale Serve entrega o Host magico
	// (nitro-v15.tailbcc368.ts.net) e o vite preview responde 403
	// ("Blocked request") sem esta permissao — com ela o webui abre
	// pelo hostname do tailnet, sem decorar IP/porta.
	preview: {
		allowedHosts: ['nitro-v15.tailbcc368.ts.net', 'nitro-v15'],
	},
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// adapter-auto only supports some environments, see https://svelte.dev/docs/kit/adapter-auto for a list.
			// If your environment is not supported, or you settled on a specific environment, switch out the adapter.
			// See https://svelte.dev/docs/kit/adapters for more information about adapters.
			adapter: adapter()
		})
	]
});
