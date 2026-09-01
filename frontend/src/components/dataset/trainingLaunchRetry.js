export async function loadLaunchCheckpoints(listCheckpoints, base, trainType) {
  let lastError
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await listCheckpoints(base, trainType)
    } catch (error) {
      lastError = error
      if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 250))
    }
  }
  throw lastError
}
