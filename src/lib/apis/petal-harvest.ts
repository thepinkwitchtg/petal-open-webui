import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { HarvestFile } from '$lib/utils/petal-harvest';

// plant a harvest bundle on the Petal rig (backend writes it under PETAL_HARVEST_DIR)
export const plantHarvest = async (token: string, folder: string, files: HarvestFile[]) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/petal/harvest`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify({ folder, files })
	});
	const json = await res.json().catch(() => ({}));
	if (!res.ok) throw json?.detail ?? `harvest failed (${res.status})`;
	return json as { path: string; files: number };
};

export const getHarvestInfo = async (token: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/petal/harvest/info`, {
		headers: { ...(token && { authorization: `Bearer ${token}` }) }
	});
	if (!res.ok) return null;
	return (await res.json()) as { root: string; exists: boolean };
};
