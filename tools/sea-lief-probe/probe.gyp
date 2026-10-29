{
  'target_defaults': {
    'default_configuration': 'Release',
    'configurations': {'Debug': {}, 'Release': {}},
  },
  'targets': [{
    'target_name': 'sea_lief_probe',
    'type': 'executable',
    'dependencies': ['../../deps/LIEF/lief.gyp:liblief'],
    'sources': ['inject.cc'],
    'defines': ['LIEF_STATIC'],
    'cflags_cc': ['-std=c++17'],
    'libraries': ['-lpthread', '-ldl'],
  }],
}
