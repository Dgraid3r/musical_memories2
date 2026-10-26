import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import type { PlaylistResult, SpotifyStatus, TrackResult } from '../types'
import CreatePlaylistPanel from './CreatePlaylistPanel'
import PlaylistSearch from './PlaylistSearch'

// Every network call goes through ../api - mocked here so no test ever
// reaches the backend (let alone Spotify or Anthropic). ApiError stays
// the real class so the component's instanceof/status checks are real.
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ApiError: actual.ApiError,
    searchTracks: vi.fn(),
    createSpotifyPlaylist: vi.fn(),
    fetchPlaylistGeneratorStatus: vi.fn(),
    generatePlaylistTracks: vi.fn(),
    getSpotifyConnectUrl: vi.fn(),
    fetchSpotifyStatus: vi.fn(),
    fetchMyPlaylists: vi.fn(),
    searchPlaylists: vi.fn(),
  }
})

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ token: 'test-token' }),
}))

const api = await import('../api')
const mocked = {
  searchTracks: vi.mocked(api.searchTracks),
  createSpotifyPlaylist: vi.mocked(api.createSpotifyPlaylist),
  fetchPlaylistGeneratorStatus: vi.mocked(api.fetchPlaylistGeneratorStatus),
  generatePlaylistTracks: vi.mocked(api.generatePlaylistTracks),
  fetchSpotifyStatus: vi.mocked(api.fetchSpotifyStatus),
}

const CAN_CREATE: SpotifyStatus = { connected: true, can_create_playlists: true }

function track(id: string, name: string, artists = 'Artist'): TrackResult {
  return {
    id,
    uri: `spotify:track:${id}`,
    name,
    artists,
    album: null,
    image_url: null,
    url: null,
    duration_ms: null,
  }
}

const BRIGHTSIDE = track('t1', 'Mr. Brightside', 'The Killers')
const FLOAT_ON = track('t2', 'Float On', 'Modest Mouse')

const CREATED: PlaylistResult = {
  id: 'newpl',
  name: 'Road trip',
  url: 'https://open.spotify.com/playlist/newpl',
  image_url: null,
  owner: 'alice',
  track_count: 2,
}

async function searchAndWait(text: string) {
  fireEvent.change(screen.getByLabelText('Add tracks'), { target: { value: text } })
  // The track search is debounced; let the timer fire and the promise settle.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
}

describe('CreatePlaylistPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.clearAllMocks()
    mocked.fetchPlaylistGeneratorStatus.mockResolvedValue({ available: false })
    mocked.searchTracks.mockResolvedValue([BRIGHTSIDE, FLOAT_ON])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('adds tracks from search to the draft and removes them again', async () => {
    render(<CreatePlaylistPanel spotifyStatus={CAN_CREATE} onCreated={vi.fn()} />)
    await searchAndWait('indie')

    expect(mocked.searchTracks).toHaveBeenCalledWith('indie')
    fireEvent.click(screen.getByRole('button', { name: 'Add Mr. Brightside by The Killers' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add Float On by Modest Mouse' }))

    const draft = screen.getByRole('list', { name: 'Playlist tracks' })
    expect(within(draft).getAllByRole('listitem')).toHaveLength(2)
    // Already-added results can't be added twice.
    expect(screen.getByRole('button', { name: 'Add Mr. Brightside by The Killers' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Remove Mr. Brightside' }))
    expect(within(draft).getAllByRole('listitem')).toHaveLength(1)
    expect(within(draft).getByText('Float On')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add Mr. Brightside by The Killers' })).toBeEnabled()
  })

  it('creates the playlist and passes the result to onCreated', async () => {
    const onCreated = vi.fn()
    mocked.createSpotifyPlaylist.mockResolvedValue(CREATED)
    render(<CreatePlaylistPanel spotifyStatus={CAN_CREATE} onCreated={onCreated} />)

    const createButton = screen.getByRole('button', { name: 'Create playlist' })
    expect(createButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Playlist name'), { target: { value: '  Road trip ' } })
    await searchAndWait('indie')
    fireEvent.click(screen.getByRole('button', { name: 'Add Mr. Brightside by The Killers' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add Float On by Modest Mouse' }))
    expect(createButton).toBeEnabled()

    fireEvent.click(createButton)
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(CREATED))
    expect(mocked.createSpotifyPlaylist).toHaveBeenCalledWith(
      'Road trip',
      ['spotify:track:t1', 'spotify:track:t2'],
      'test-token',
    )
  })

  it('shows a reconnect prompt when the server says the token lacks write scope', async () => {
    const onCreated = vi.fn()
    mocked.createSpotifyPlaylist.mockRejectedValue(new ApiError(403, 'Reconnect Spotify to create playlists.'))
    render(<CreatePlaylistPanel spotifyStatus={CAN_CREATE} onCreated={onCreated} />)

    fireEvent.change(screen.getByLabelText('Playlist name'), { target: { value: 'Road trip' } })
    await searchAndWait('indie')
    fireEvent.click(screen.getByRole('button', { name: 'Add Mr. Brightside by The Killers' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create playlist' }))

    expect(await screen.findByText('Reconnect Spotify to create playlists.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reconnect Spotify' })).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('prompts a reconnect up front for an account linked before playlist creation existed', () => {
    render(
      <CreatePlaylistPanel spotifyStatus={{ connected: true, can_create_playlists: false }} onCreated={vi.fn()} />,
    )
    expect(screen.getByText('Reconnect Spotify to create playlists.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reconnect Spotify' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create playlist' })).toBeDisabled()
  })

  it('prompts a connect when no Spotify account is linked', () => {
    render(
      <CreatePlaylistPanel spotifyStatus={{ connected: false, can_create_playlists: false }} onCreated={vi.fn()} />,
    )
    expect(screen.getByText('Connect Spotify to create playlists.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Spotify' })).toBeInTheDocument()
  })

  it('hides "Generate from a prompt" when the server has no generator configured', async () => {
    render(<CreatePlaylistPanel spotifyStatus={CAN_CREATE} onCreated={vi.fn()} />)
    await waitFor(() => expect(mocked.fetchPlaylistGeneratorStatus).toHaveBeenCalled())
    await act(async () => {})
    expect(screen.queryByRole('button', { name: 'Generate from a prompt' })).not.toBeInTheDocument()
  })

  it('shows "Generate from a prompt" when available, toggles the prompt box, and pre-fills matches', async () => {
    mocked.fetchPlaylistGeneratorStatus.mockResolvedValue({ available: true })
    mocked.generatePlaylistTracks.mockResolvedValue({
      matched: [BRIGHTSIDE, FLOAT_ON],
      unmatched: [{ title: 'Imaginary Song', artist: 'Nobody' }],
    })
    render(<CreatePlaylistPanel spotifyStatus={CAN_CREATE} onCreated={vi.fn()} />)

    const toggle = await screen.findByRole('button', { name: 'Generate from a prompt' })
    expect(screen.queryByLabelText('Describe the mood or theme')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    fireEvent.change(screen.getByLabelText('Describe the mood or theme'), {
      target: { value: 'rainy night drive' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Suggest songs' }))

    const draft = await screen.findByRole('list', { name: 'Playlist tracks' })
    expect(within(draft).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('Imaginary Song - Nobody')).toBeInTheDocument()
    expect(mocked.generatePlaylistTracks).toHaveBeenCalledWith('rainy night drive', 'test-token')

    // Generated tracks are removable like any other draft track.
    fireEvent.click(screen.getByRole('button', { name: 'Remove Float On' }))
    expect(within(draft).getAllByRole('listitem')).toHaveLength(1)

    fireEvent.click(toggle)
    expect(screen.queryByLabelText('Describe the mood or theme')).not.toBeInTheDocument()
  })
})

describe('PlaylistSearch "Create new playlist" option', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.fetchPlaylistGeneratorStatus.mockResolvedValue({ available: false })
    mocked.fetchSpotifyStatus.mockResolvedValue(CAN_CREATE)
  })

  it('opens the create panel and hands the created playlist to onSelect', async () => {
    const onSelect = vi.fn()
    mocked.searchTracks.mockResolvedValue([BRIGHTSIDE])
    mocked.createSpotifyPlaylist.mockResolvedValue(CREATED)
    render(<PlaylistSearch selected={null} onSelect={onSelect} />)

    fireEvent.click(screen.getByRole('button', { name: 'Create new playlist' }))
    fireEvent.change(screen.getByLabelText('Playlist name'), { target: { value: 'Road trip' } })
    fireEvent.change(screen.getByLabelText('Add tracks'), { target: { value: 'brightside' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Add Mr. Brightside by The Killers' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create playlist' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Create playlist' }))

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(CREATED))
    // Back on the search view once the new playlist is selected.
    expect(screen.queryByLabelText('Playlist name')).not.toBeInTheDocument()
  })
})
