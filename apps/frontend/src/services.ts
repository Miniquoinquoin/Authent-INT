/**
 * The services behind the portal tiles. `endpoint` answers `{ [listKey]: rows }`
 * (apps/mock-services/src/mockservices/resources.py); `columns` picks what the page shows.
 */
import { CADASTRE_URL, IMPOTS_URL } from './config'

export interface Service {
  id: string
  title: string
  description: string
  read: string
  write: string
  endpoint: string
  listKey: string
  columns: { key: string; label: string }[]
}

export const SERVICES: Service[] = [
  {
    id: 'impots',
    title: 'Impôts',
    description: 'Vos dossiers fiscaux : déclarations, avis et paiements.',
    read: 'svc:impots.read',
    write: 'svc:impots.write',
    endpoint: `${IMPOTS_URL}/dossiers`,
    listKey: 'dossiers',
    columns: [
      { key: 'id', label: 'Référence' },
      { key: 'impot', label: 'Impôt' },
      { key: 'annee', label: 'Année' },
      { key: 'statut', label: 'Statut' },
      { key: 'montant_eur', label: 'Montant (€)' },
    ],
  },
  {
    id: 'cadastre',
    title: 'Cadastre',
    description: 'Le plan cadastral et les informations sur les parcelles.',
    read: 'svc:cadastre.read',
    write: 'svc:cadastre.write',
    endpoint: `${CADASTRE_URL}/parcelles`,
    listKey: 'parcelles',
    columns: [
      { key: 'id', label: 'Parcelle' },
      { key: 'commune', label: 'Commune' },
      { key: 'contenance_m2', label: 'Surface (m²)' },
      { key: 'nature', label: 'Nature' },
    ],
  },
]
