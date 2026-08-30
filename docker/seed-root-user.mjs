import Group from '/app/lib/group/index.js'
import User from '/app/lib/user/index.js'

const groupId = 1
const username = 'root'

function required(name) {
  const value = process.env[name]
  if (!value) throw new Error(`${name} must be set to create the root user`)
  return value
}

try {
  const groups = await Group.get({ id: groupId })
  if (groups.length !== 1) throw new Error(`NicTool group ${groupId} is missing`)

  const existing = await User.get({ gid: groupId, username })
  if (existing.length > 0) {
    console.log('root user already exists')
  } else {
    const id = await User.create({
      gid: groupId,
      username,
      email: required('ROOT_USER_EMAIL'),
      password: required('ROOT_USER_PASSWORD'),
      first_name: 'Root',
      last_name: 'User',
    })
    if (!id) throw new Error('root user creation failed')
    console.log(`created root user ${id}`)
  }
} finally {
  await User.disconnect()
}
