import combine
import dynasty_daddy
import dynastydealer
import dynastyprocess
import fantasycalc
import fantasypros
import ktc
import rosteraudit

if __name__ == "__main__":
    for source in [ktc, fantasycalc, dynastyprocess, rosteraudit, dynasty_daddy, dynastydealer, fantasypros]:
        source.pull()
    combine.combine()
