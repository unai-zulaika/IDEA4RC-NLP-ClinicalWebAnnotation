// Color palette for different prompt types
export const PROMPT_COLORS: Record<string, string> = {
  'gender-int': '#3b82f6', // blue
  'biopsygrading-int': '#10b981', // green
  'surgerymargins-int': '#f59e0b', // amber
  'tumordepth-int': '#8b5cf6', // purple
  'histological-tipo-int': '#ec4899', // pink
  'stage_at_diagnosis-int': '#06b6d4', // cyan
  'patient-status-int': '#14b8a6', // teal
  'biopsymitoticcount-int': '#ef4444', // red
  'reexcision-int': '#84cc16', // lime
  'necrosis_in_biopsy-int': '#f97316', // orange
  'chemotherapy_start-int': '#6366f1', // indigo
  'radiotherapy_start-int': '#14b8a6', // teal
  'radiotherapy_end-int': '#06b6d4', // cyan
}

const DEFAULT_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', 
  '#06b6d4', '#14b8a6', '#ef4444', '#84cc16', '#f97316'
]

// Generate a color for a prompt type (deterministic based on hash)
export function getColorForPromptType(promptType: string): string {
  if (PROMPT_COLORS[promptType]) {
    return PROMPT_COLORS[promptType]
  }
  // Generate deterministic color based on prompt type name
  let hash = 0
  for (let i = 0; i < promptType.length; i++) {
    hash = promptType.charCodeAt(i) + ((hash << 5) - hash)
  }
  return DEFAULT_COLORS[Math.abs(hash) % DEFAULT_COLORS.length]
}

// Convert hex color to Tailwind-compatible color classes
// Returns an object with background, text, and border color classes
export function getColorClassesForPromptType(promptType: string): {
  bg: string
  text: string
  border: string
  bgLight: string
  textDark: string
} {
  const color = getColorForPromptType(promptType)
  
  // Map hex colors to Tailwind classes
  const colorMap: Record<string, { bg: string; text: string; border: string; bgLight: string; textDark: string }> = {
    '#3b82f6': { bg: 'bg-blue-500', text: 'text-blue-500', border: 'border-blue-500', bgLight: 'bg-blue-50', textDark: 'text-blue-800' }, // blue
    '#10b981': { bg: 'bg-green-500', text: 'text-green-500', border: 'border-green-500', bgLight: 'bg-green-50', textDark: 'text-green-800' }, // green
    '#f59e0b': { bg: 'bg-amber-500', text: 'text-amber-500', border: 'border-amber-500', bgLight: 'bg-amber-50', textDark: 'text-amber-800' }, // amber
    '#8b5cf6': { bg: 'bg-purple-500', text: 'text-purple-500', border: 'border-purple-500', bgLight: 'bg-purple-50', textDark: 'text-purple-800' }, // purple
    '#ec4899': { bg: 'bg-pink-500', text: 'text-pink-500', border: 'border-pink-500', bgLight: 'bg-pink-50', textDark: 'text-pink-800' }, // pink
    '#06b6d4': { bg: 'bg-cyan-500', text: 'text-cyan-500', border: 'border-cyan-500', bgLight: 'bg-cyan-50', textDark: 'text-cyan-800' }, // cyan
    '#14b8a6': { bg: 'bg-teal-500', text: 'text-teal-500', border: 'border-teal-500', bgLight: 'bg-teal-50', textDark: 'text-teal-800' }, // teal
    '#ef4444': { bg: 'bg-red-500', text: 'text-red-500', border: 'border-red-500', bgLight: 'bg-red-50', textDark: 'text-red-800' }, // red
    '#84cc16': { bg: 'bg-lime-500', text: 'text-lime-500', border: 'border-lime-500', bgLight: 'bg-lime-50', textDark: 'text-lime-800' }, // lime
    '#f97316': { bg: 'bg-orange-500', text: 'text-orange-500', border: 'border-orange-500', bgLight: 'bg-orange-50', textDark: 'text-orange-800' }, // orange
    '#6366f1': { bg: 'bg-indigo-500', text: 'text-indigo-500', border: 'border-indigo-500', bgLight: 'bg-indigo-50', textDark: 'text-indigo-800' }, // indigo
  }
  
  // Return mapped colors or default to gray
  return colorMap[color] || { bg: 'bg-gray-500', text: 'text-gray-500', border: 'border-gray-500', bgLight: 'bg-gray-50', textDark: 'text-gray-800' }
}

