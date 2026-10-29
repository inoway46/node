#include <LIEF/ELF.hpp>

#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

// A standalone reproduction of InjectIntoELF() and MarkSentinel() in
// src/node_sea_bin.cc, built against the repository's bundled LIEF.
int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: sea_lief_probe NODE BLOB OUTPUT\n";
    return 1;
  }
  auto binary = LIEF::ELF::Parser::parse(argv[1]);
  if (!binary ||
      binary->header().file_type() != LIEF::ELF::Header::FILE_TYPE::EXEC) {
    std::cerr << "expected a non-PIE ELF executable\n";
    return 1;
  }
  std::ifstream input(argv[2], std::ios::binary);
  if (!input) return 1;
  const std::vector<uint8_t> blob{std::istreambuf_iterator<char>(input),
                                  std::istreambuf_iterator<char>()};
  if (blob.empty()) return 1;
  auto note =
      LIEF::ELF::Note::create("NODE_SEA_BLOB", 0, blob, ".note.node.sea");
  if (!note || binary->relocate_phdr_table(
                   LIEF::ELF::Binary::PHDR_RELOC::BSS_END) == 0) {
    std::cerr << "could not create note or relocate program headers\n";
    return 1;
  }
  binary->add(*note);
  LIEF::ELF::Builder::config_t config;
  config.notes = true;
  config.dynamic_section = true;
  LIEF::ELF::Builder builder(*binary, config);
  builder.build();
  const auto& bytes = builder.get_build();
  if (bytes.empty()) return 1;
  std::string output(bytes.begin(), bytes.end());
  const std::string sentinel = "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2";
  const auto at = output.find(sentinel);
  if (at == std::string::npos || at != output.rfind(sentinel) ||
      output.compare(at + sentinel.size(), 2, ":0") != 0) {
    std::cerr << "expected exactly one inactive SEA fuse\n";
    return 1;
  }
  output[at + sentinel.size() + 1] = '1';
  std::ofstream file(argv[3], std::ios::binary);
  file.write(output.data(), output.size());
  file.close();
  return file ? 0 : 1;
}
